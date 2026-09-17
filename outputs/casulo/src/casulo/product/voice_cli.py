from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .platform_contracts import PlatformError
from .voice_adopt import adopt_voice_candidate
from .voice_build import build_voice_bridge
from .voice_candidate import VoiceCandidate, candidate_doctor_report
from .voice_smoke import smoke_cached_whisper
from .voice_physical import (
    BARGE_IN_CONSENT,
    CAPTURE_CONSENT,
    PLAYBACK_CONSENT,
    capture_microphone_smoke,
    barge_in_smoke,
    playback_cancel_smoke,
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casulo-voice")
    subcommands = parser.add_subparsers(dest="command", required=True)
    doctor = subcommands.add_parser("doctor", help="inspeção somente leitura da voz local")
    doctor.add_argument(
        "--manifest",
        type=Path,
        default=_repository_root() / "release/voice-candidates/whisper-cpp-v1.9.2.json",
    )
    doctor.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/voice",
    )
    build = subcommands.add_parser(
        "build-asr",
        help="compila cache já verificado; nunca baixa dependências",
    )
    build.add_argument(
        "--manifest",
        type=Path,
        default=_repository_root() / "release/voice-candidates/whisper-cpp-v1.9.2.json",
    )
    build.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/voice",
    )
    build.add_argument("--repository", type=Path, default=_repository_root())
    adopt = subcommands.add_parser(
        "adopt-asr",
        help="download transacional com consentimento literal",
    )
    adopt.add_argument(
        "--manifest",
        type=Path,
        default=_repository_root() / "release/voice-candidates/whisper-cpp-v1.9.2.json",
    )
    adopt.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/voice",
    )
    adopt.add_argument("--consent", required=True)
    smoke = subcommands.add_parser(
        "smoke-asr",
        help="valida boundary real com silêncio sintético; não abre dispositivos",
    )
    smoke.add_argument(
        "--manifest",
        type=Path,
        default=_repository_root() / "release/voice-candidates/whisper-cpp-v1.9.2.json",
    )
    smoke.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/voice",
    )
    smoke.add_argument("--seconds", type=float, default=1.0)
    smoke.add_argument("--threads", type=int, default=1)
    capture = subcommands.add_parser(
        "capture-smoke",
        help="abre microfone por janela limitada; nunca persiste PCM",
    )
    capture.add_argument(
        "--manifest",
        type=Path,
        default=_repository_root() / "release/voice-candidates/whisper-cpp-base-q5_1-v1.9.2.json",
    )
    capture.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/voice",
    )
    capture.add_argument("--seconds", type=float, default=8.0)
    capture.add_argument("--threads", type=int, default=4)
    capture.add_argument("--device", type=int)
    capture.add_argument("--consent", required=True, help=f"use exatamente {CAPTURE_CONSENT}")
    playback = subcommands.add_parser(
        "playback-smoke",
        help="toca voz local por até 3 s e comprova cancelamento",
    )
    playback.add_argument("--seconds", type=float, default=2.0)
    playback.add_argument("--consent", required=True, help=f"use exatamente {PLAYBACK_CONSENT}")
    barge = subcommands.add_parser(
        "barge-in-smoke",
        help="prova física voz -> cancelamento; nunca persiste PCM",
    )
    barge.add_argument(
        "--manifest",
        type=Path,
        default=_repository_root() / "release/voice-candidates/whisper-cpp-base-q5_1-v1.9.2.json",
    )
    barge.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/voice",
    )
    barge.add_argument("--seconds", type=float, default=15.0)
    barge.add_argument("--threads", type=int, default=4)
    barge.add_argument("--device", type=int)
    barge.add_argument("--report", type=Path)
    barge.add_argument("--consent", required=True, help=f"use exatamente {BARGE_IN_CONSENT}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        try:
            candidate = VoiceCandidate.load(args.manifest)
            report = candidate_doctor_report(candidate, args.cache)
        except PlatformError as error:
            print(json.dumps({"schema": "casulo-voice-doctor/1.0", "error": str(error)}, ensure_ascii=False))
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["ready"] else 3
    if args.command == "build-asr":
        try:
            candidate = VoiceCandidate.load(args.manifest)
            report = build_voice_bridge(candidate, args.cache, args.repository)
        except PlatformError as error:
            print(json.dumps({"schema": "casulo-voice-build/1.0", "error": str(error)}, ensure_ascii=False))
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "adopt-asr":
        try:
            candidate = VoiceCandidate.load(args.manifest)
            report = adopt_voice_candidate(
                candidate,
                args.cache,
                consent=args.consent,
            )
        except PlatformError as error:
            print(json.dumps({"schema": "casulo-voice-adoption/1.0", "error": str(error)}, ensure_ascii=False))
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "smoke-asr":
        try:
            candidate = VoiceCandidate.load(args.manifest)
            report = smoke_cached_whisper(
                candidate,
                args.cache,
                seconds=args.seconds,
                threads=args.threads,
            )
        except PlatformError as error:
            print(json.dumps({"schema": "casulo-asr-smoke/1.0", "error": str(error)}, ensure_ascii=False))
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "capture-smoke":
        try:
            candidate = VoiceCandidate.load(args.manifest)
            report = capture_microphone_smoke(
                candidate,
                args.cache,
                consent=args.consent,
                duration_s=args.seconds,
                threads=args.threads,
                device=args.device,
            )
        except PlatformError as error:
            print(json.dumps({"schema": "casulo-physical-capture-smoke/1.0", "error": str(error)}, ensure_ascii=False))
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["passed"] else 4
    if args.command == "playback-smoke":
        try:
            report = playback_cancel_smoke(
                consent=args.consent,
                audible_s=args.seconds,
            )
        except PlatformError as error:
            print(json.dumps({"schema": "casulo-physical-playback-smoke/1.0", "error": str(error)}, ensure_ascii=False))
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["passed"] else 4
    if args.command == "barge-in-smoke":
        try:
            candidate = VoiceCandidate.load(args.manifest)
            report = barge_in_smoke(
                candidate,
                args.cache,
                consent=args.consent,
                duration_s=args.seconds,
                threads=args.threads,
                device=args.device,
            )
        except PlatformError as error:
            print(json.dumps({"schema": "casulo-physical-barge-in-smoke/1.0", "error": str(error)}, ensure_ascii=False))
            return 2
        if args.report is not None:
            destination = args.report.expanduser().resolve()
            if destination.suffix.casefold() != ".json" or not destination.parent.is_dir():
                raise PlatformError("destino do recibo precisa ser JSON em diretório existente")
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(destination)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["passed"] else 4
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
