from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from interlocution.worker import build_primitive_manifest, run_governed_worker


CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"


def write_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != value:
            raise FileExistsError(f"append-only artifact differs: {path}")
        return
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--output", type=Path, default=CAMPAIGN / "receipts/full-worker-smoke")
    args = parser.parse_args()
    primitive = build_primitive_manifest(
        executable=FULL / "worker/tcap_full_worker.exe",
        source=FULL / "worker/tcap_full_worker.rs",
        tcap=FULL / "artifact/FloodSurrogate.full.tcap",
    )
    manifest_path = CAMPAIGN / "primitive-manifest.json"
    write_once(manifest_path, primitive)
    result = run_governed_worker(
        grant_file=CAMPAIGN / "authority-grant.json",
        authority_receipt_file=CAMPAIGN / "receipts/policy-authority.jsonl",
        primitive_manifest_file=manifest_path,
        executable=FULL / "worker/tcap_full_worker.exe",
        dataset=FULL / "artifact/FloodSurrogate.dataset.bin",
        initializations=FULL / "artifact/FloodSurrogate.initializations.bin",
        output_directory=args.output,
        count=args.count,
    )
    print(json.dumps(result.summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

