from __future__ import annotations

import argparse
import hashlib
import json

from .guide_presence import GuidePresence, JobEvent, JobStatus
from .hosted_shell import HostedShell, ProductFeature
from .platform_contracts import (
    BufferedAudioPlayback,
    ConsoleDisplay,
    SyntheticAudioCapture,
    SystemClock,
    VoiceEvent,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice hosted sintético do Casulo")
    parser.add_argument(
        "--utterance",
        default="Quero criar um guia que preserve a continuidade dos meus projetos.",
    )
    args = parser.parse_args()

    capture = SyntheticAudioCapture()
    playback = BufferedAudioPlayback()
    display = ConsoleDisplay(emit_ansi=False)
    clock = SystemClock()
    guide = GuidePresence(clock=clock)
    shell = HostedShell(
        clock=clock,
        capture=capture,
        playback=playback,
        display=display,
        features=frozenset({ProductFeature.MINIMAL}),
        guide=guide,
    )
    shell.boot()
    evidence_sha256 = hashlib.sha256(b"hosted-demo-index-opened").hexdigest()
    shell.accept_job_event(
        JobEvent(
            event_id="job:index:start",
            job_id="job:index",
            status=JobStatus.STARTED,
            summary="Marco real: índice aberto",
            evidence_sha256=evidence_sha256,
            source_event_ids=("demo:request",),
            occurred_at=clock.utc_timestamp(),
        )
    )
    capture.emit(VoiceEvent("voice:1", args.utterance, "pt-BR", final=True))
    shell.poll_voice()
    execution_order = [shell.run_one(), shell.run_one()]
    interrupted = shell.interrupt_guide()
    print(
        json.dumps(
            {
                "ok": True,
                "audio_source": "synthetic-not-asr",
                "execution_order": execution_order,
                "presence_preempted_background": execution_order[0] == "VOICE",
                "guide_playback_interrupted": interrupted,
                "guide_mode": guide.mode.value,
                "active_background_jobs": guide.active_job_count,
                "progress_evidence_sha256": evidence_sha256,
                "creation": shell.creation.current.to_dict(),
                "frames": [frame.__dict__ if hasattr(frame, "__dict__") else {
                    "state": frame.state,
                    "semantic_color": frame.semantic_color,
                    "certainty": frame.certainty,
                    "summary": frame.summary,
                    "sequence": frame.sequence,
                } for frame in display.frames],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
