from __future__ import annotations

import argparse
import json

from .hosted_shell import HostedShell, ProductFeature
from .platform_contracts import (
    BufferedAudioPlayback,
    ConsoleDisplay,
    SyntheticAudioCapture,
    SystemClock,
    VoiceEvent,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="IntentDelta -> T Forge incremental")
    parser.add_argument("--utterance", default="defina behavior.tone como direto")
    args = parser.parse_args()
    capture = SyntheticAudioCapture()
    display = ConsoleDisplay(emit_ansi=False)
    shell = HostedShell(
        clock=SystemClock(),
        capture=capture,
        playback=BufferedAudioPlayback(),
        display=display,
        features=frozenset({ProductFeature.CREATOR}),
    )
    assert shell.last_forge_receipt is not None
    before = {
        artifact.unit_id: artifact.artifact_sha256
        for artifact in shell.last_forge_receipt.artifacts
    }
    capture.emit(VoiceEvent("voice:proposal", args.utterance, "pt-BR", True))
    shell.poll_voice()
    shell.run_one()
    proposed_version = shell.creation.current.version
    proposed_content = dict(shell.creation.current.content)
    capture.emit(VoiceEvent("voice:confirmation", "confirmo", "pt-BR", True))
    shell.poll_voice()
    shell.run_one()
    assert shell.last_forge_receipt is not None
    after = {
        artifact.unit_id: artifact.artifact_sha256
        for artifact in shell.last_forge_receipt.artifacts
    }
    print(
        json.dumps(
            {
                "schema": "casulo.intent-forge-demo/1.0",
                "ok": True,
                "audio_source": "synthetic-not-asr",
                "proposal_did_not_mutate_content": proposed_content == {},
                "proposed_version": proposed_version,
                "creation": shell.creation.current.to_dict(),
                "forge": shell.last_forge_receipt.to_dict(),
                "unchanged_units": sorted(
                    unit_id for unit_id, digest in before.items() if after[unit_id] == digest
                ),
                "changed_units": sorted(
                    unit_id for unit_id, digest in before.items() if after[unit_id] != digest
                ),
                "frames": [
                    {
                        "state": frame.state,
                        "certainty": frame.certainty,
                        "summary": frame.summary,
                        "sequence": frame.sequence,
                    }
                    for frame in display.frames
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
