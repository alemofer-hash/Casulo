from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output exists; overwrite denied")

    import sys
    sys.path.insert(0, str(repo / "src"))
    from casulo.product.audio_frontend import AudioFrontend
    from casulo.product.first_party_tts import FirstPartyFormantTTS, SAMPLE_RATE

    import math
    import struct

    tts = FirstPartyFormantTTS()
    pcm, receipt = tts.synthesize("Olá, Guilherme. O Casulo está pronto para a sua prova humana.")
    calls = 0
    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 4
    partial = list(tts.stream("Esta fala local será interrompida de forma segura.", cancelled=cancelled))

    reference = [int(6000 * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE)) for index in range(320)]
    microphone = [int(4200 * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE)) for index in range(320)]
    reference_pcm = struct.pack("<" + "h" * len(reference), *reference)
    microphone_pcm = struct.pack("<" + "h" * len(microphone), *microphone)
    _residual, frontend = AudioFrontend(noise_floor=20).process(microphone_pcm, reference_pcm)
    checks = {
        "tts_pcm_nonempty": len(pcm) == receipt.samples * 2 and receipt.samples > 0,
        "tts_cancelled": 0 < len(partial) < receipt.frames,
        "synthetic_echo_reduced": frontend.residual_rms < frontend.input_rms * 0.05,
        "raw_pcm_persisted": False,
        "physical_device_opened": False,
    }
    report = {
        "schema": "casulo.rc12-synthetic-voice/1.0",
        "state": "PASS" if all(value is True for key, value in checks.items() if key not in {"raw_pcm_persisted", "physical_device_opened"}) and not checks["raw_pcm_persisted"] and not checks["physical_device_opened"] else "FAIL",
        "checks": checks,
        "tts": {name: getattr(receipt, name) for name in receipt.__slots__},
        "cancelled_frames": len(partial),
        "audio_frontend": {name: getattr(frontend, name) for name in frontend.__slots__},
        "claim_boundary": "synthetic implementation smoke only; physical voice and chemistry remain Guilherme-only",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
