from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verificador independente do arquivo estrutural Casulo."
    )
    parser.add_argument("archive")
    parser.add_argument("--output")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    _bootstrap()
    from casulo.compression.independent_structural import (  # noqa: PLC0415
        IndependentReconstructionError,
        reconstruct_independently,
    )

    try:
        result = reconstruct_independently(
            args.archive,
            args.output,
            overwrite=args.overwrite,
        )
    except (IndependentReconstructionError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
