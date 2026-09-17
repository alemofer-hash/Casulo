from __future__ import annotations

import argparse
import json
from pathlib import Path

from .generative_model import (
    GenerativeCandidate,
    GenerativeModelError,
    adopt_candidate,
    adoption_doctor,
    adoption_plan,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Casulo owner generative model doctor/adoption")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "plan", "adopt"):
        command = sub.add_parser(name)
        command.add_argument("--candidate", type=Path, required=True)
        command.add_argument("--cache", type=Path, required=True)
        if name == "adopt":
            command.add_argument("--consent", required=True)
    args = parser.parse_args(argv)
    try:
        candidate = GenerativeCandidate.load(args.candidate)
        if args.command == "doctor":
            result = adoption_doctor(candidate, args.cache)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if result["ready"] else 2
        if args.command == "plan":
            print(json.dumps(adoption_plan(candidate, args.cache), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        result = adopt_candidate(candidate, args.cache, consent=args.consent)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except GenerativeModelError as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
