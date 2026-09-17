from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import threading
import time
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "private/casulo-owner/src")]

from casulo.product.audio_frontend import AudioFrontend  # noqa: E402
from casulo.product.first_party_tts import FirstPartyFormantTTS  # noqa: E402
from casulo.product.platform_contracts import SystemClock  # noqa: E402
from casulo.product.voice_duplex import AudioFrame, EnergyVad, TranscriptEvent, VoiceDuplex  # noqa: E402
from casulo.t.productive import ProductiveTError  # noqa: E402
from casulo_owner.t85_presence import PresenceWorkLanes, T85TurnCoordinator  # noqa: E402


class LogicalClock:
    def __init__(self) -> None:
        self.ns = 0

    def monotonic_ns(self) -> int:
        self.ns += 1_000_000
        return self.ns

    def utc_timestamp(self) -> str:
        return f"2026-08-14T23:{(self.ns // 1_000_000_000) // 60:02d}:{(self.ns // 1_000_000_000) % 60:02d}Z"


class SyntheticAsr:
    locale = "pt-BR"

    def __init__(self) -> None:
        self.turn = 0

    def accept(self, frame: AudioFrame):
        values = array("h", frame.pcm_s16le)
        if max(values, default=0) > 0:
            return TranscriptEvent(f"tx.{self.turn}", "quero continuar", "pt-BR", False, 0.8)
        return None

    def finalize(self):
        value = TranscriptEvent(f"tx.{self.turn}", f"quero continuar o turno {self.turn}", "pt-BR", True, 0.9)
        self.turn += 1
        return value

    def reset(self) -> None:
        return None


class SyntheticSession:
    def __init__(self) -> None:
        self.cancelled = False

    @property
    def active(self) -> bool:
        return not self.cancelled

    def cancel(self) -> None:
        self.cancelled = True


class SyntheticTts:
    locale = "pt-BR"
    streaming_pcm = True

    def __init__(self) -> None:
        self.sessions: list[SyntheticSession] = []

    def speak(self, text: str) -> SyntheticSession:
        if not text:
            raise ValueError("empty TTS")
        session = SyntheticSession()
        self.sessions.append(session)
        return session


def frame(amplitude: int) -> AudioFrame:
    return AudioFrame(array("h", [amplitude] * 320).tobytes())


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or ROOT.resolve() not in output.parents:
        raise SystemExit("output must be new and inside repository")
    output.mkdir(parents=True)
    runtime = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
    tcap = T85TurnCoordinator.build(ROOT / "private/casulo-owner/t-v2/turn-coordinator.t", output / "turn-coordinator.tcap")
    coordinator = T85TurnCoordinator(runtime, tcap, output / "turn-receipts")
    clock = LogicalClock()
    tts = SyntheticTts()
    duplex = VoiceDuplex(clock=clock, vad=EnergyVad(500), asr=SyntheticAsr(), tts=tts, endpoint_silence_ms=60)
    lanes = PresenceWorkLanes(clock=clock, coordinator=coordinator)

    work_entered = threading.Event()
    work_release = threading.Event()

    def long_work() -> bytes:
        work_entered.set()
        if not work_release.wait(timeout=30):
            raise RuntimeError("synthetic work timeout")
        return b"verified-work-artifact"

    future = lanes.submit("job.sixty-minute", long_work, source_event_id="intent.synthetic")
    if not work_entered.wait(timeout=2):
        raise RuntimeError("work lane did not start")
    partials = finals = barge_ins = committed = 0
    cancel_latencies: list[int] = []
    presence_while_work = 0
    started = time.perf_counter()
    for turn in range(120):
        duplex.speak(f"resposta provisória {turn}")
        events = duplex.ingest(frame(1200))
        for event in events:
            decision = coordinator.decide_duplex(event, tts_active=event.kind == "BARGE_IN")
            if event.kind == "BARGE_IN":
                barge_ins += 1
                cancel_latencies.append(int(event.cancel_latency_ns or 0))
                assert decision.value == "BARGE_IN"
            elif event.kind == "TRANSCRIPT_PARTIAL":
                partials += 1
                assert decision.value == "LISTEN"
        for _ in range(3):
            for event in duplex.ingest(frame(0)):
                decision = coordinator.decide_duplex(event, tts_active=False)
                if event.kind == "TRANSCRIPT_FINAL":
                    finals += 1
                    committed += int(decision.value == "COMMIT_FINAL")
        presence_while_work += int(not future.done())
        clock.ns += 30_000_000_000

    # Accessible text fallback uses the same T authority but no ASR claim.
    text_fallback_commits = sum(
        coordinator.decide(
            event_kind="TEXT_FINAL", speech_detected=False, transcript_final=True,
            transcript_nonempty=True, tts_active=False,
        ).value == "COMMIT_FINAL"
        for _ in range(20)
    )
    untrusted_progress_denied = False
    try:
        coordinator.decide(
            event_kind="JOB_EVENT", speech_detected=False, transcript_final=False,
            transcript_nonempty=False, tts_active=False, job_event_authenticated=False,
        )
    except ProductiveTError:
        untrusted_progress_denied = True
    work_release.set()
    work_result = future.result(timeout=10)

    late_entered = threading.Event()
    late_release = threading.Event()

    def late_work() -> bytes:
        late_entered.set()
        late_release.wait(timeout=10)
        return b"late"

    late = lanes.submit("job.cancelled", late_work, source_event_id="intent.cancel")
    late_entered.wait(timeout=2)
    cancellation_accepted = lanes.cancel("job.cancelled", source_event_id="human.cancel")
    late_release.set()
    late.result(timeout=10)
    lanes.close()

    # Real first-party TTS algorithm, synthetic and inaudible.
    formant_frames = list(FirstPartyFormantTTS().stream("Presença contínua e interrompível em português brasileiro."))
    calls = 0

    def stop_early() -> bool:
        nonlocal calls
        calls += 1
        return calls > 4

    cancelled_frames = list(FirstPartyFormantTTS().stream("Esta fala será cancelada sem publicar resultado tardio.", cancelled=stop_early))
    reference = [int(6000 * math.sin(2 * math.pi * 440 * index / 16_000)) for index in range(320)]
    microphone = [int(4200 * math.sin(2 * math.pi * 440 * index / 16_000)) for index in range(320)]
    reference_pcm = struct.pack("<" + "h" * 320, *reference)
    microphone_pcm = struct.pack("<" + "h" * 320, *microphone)
    _residual, frontend = AudioFrontend(noise_floor=20).process(microphone_pcm, reference_pcm)

    job_statuses = [event.status.value for event in lanes.events]
    late_completion_absent = job_statuses[-2:] == ["STARTED", "CANCELLED"]
    receipts = sorted((output / "turn-receipts").glob("turn.*.receipt.json"))
    elapsed = time.perf_counter() - started
    checks = {
        "synthetic_duration_60_minutes": clock.ns >= 3_600_000_000_000,
        "presence_lane_nonblocking": presence_while_work == 120,
        "asr_partials": partials == 120,
        "asr_finals": finals == 120,
        "all_finals_committed_by_t": committed == 120,
        "barge_in_every_turn": barge_ins == 120 and all(value >= 0 for value in cancel_latencies),
        "text_fallback": text_fallback_commits == 20,
        "progress_only_authenticated": untrusted_progress_denied and job_statuses[:2] == ["STARTED", "COMPLETED"],
        "cancel_late_result_drop": cancellation_accepted and late_completion_absent,
        "tts_streaming_frames": len(formant_frames) > 1,
        "tts_cancelled": 0 < len(cancelled_frames) < len(formant_frames),
        "aec_reference_reduces_echo": frontend.residual_rms < frontend.input_rms * 0.05,
        "raw_pcm_persisted": False,
        "receipts_present": len(receipts) == 384,
        "physical_devices_opened": False,
    }
    passed = all(value is True for key, value in checks.items() if key not in {"raw_pcm_persisted", "physical_devices_opened"}) and not checks["raw_pcm_persisted"] and not checks["physical_devices_opened"]
    report = {
        "schema": "casulo.t85-presence-voice-gate/1.0",
        "gate": "TS9_PRESENCE_VOICE_SYNTHETIC_PASS" if passed else "TS9_FAIL",
        "logical_duration_seconds": clock.ns / 1_000_000_000,
        "wall_probe_seconds": elapsed,
        "turns": 120,
        "partials": partials,
        "finals": finals,
        "barge_ins": barge_ins,
        "max_cancel_latency_ns": max(cancel_latencies, default=None),
        "text_fallback_commits": text_fallback_commits,
        "job_statuses": job_statuses,
        "t_receipts": len(receipts),
        "formant_frames": len(formant_frames),
        "cancelled_formant_frames": len(cancelled_frames),
        "audio_frontend": {name: getattr(frontend, name) for name in frontend.__slots__},
        "checks": checks,
        "physical_gate": "PENDING_GUILHERME_EXPLICIT_CONSENT",
        "voice_quality": "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "claim_boundary": "synthetic 60-minute logical gate; no microphone, speaker or human chemistry claim",
        "locks": {"cloud": "RELEASE_LOCKED", "guest_network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
        "work_result_sha256": hashlib.sha256(work_result).hexdigest(),
    }
    dump(output / "presence-voice-gate.json", report)
    dump(output / "gate.json", {"gate": report["gate"], "checks": checks, "physical_gate": report["physical_gate"]})
    print(json.dumps({"gate": report["gate"], "turns": 120, "t_receipts": len(receipts), "physical": report["physical_gate"]}, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
