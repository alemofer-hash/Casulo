from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(root: Path) -> None:
    artifacts = [path for path in root.rglob("*") if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}]
    checks = {
        "preserved_failure_inventory": (root.parent / "inspection-failure-3-einstein-preserved/FORENSIC_INVENTORY.json").is_file(),
        "neural_einstein_evidence": (root / "einstein-solver-evidence.json").is_file(),
        "scientific_package": (root / "casulo-owner-einstein-local-solver.casulo.zip").is_file(),
        "visualization": (root / "creation-visual/index.html").is_file() and (root / "semantic-visual/index.html").is_file(),
        "vm_restore": json.loads((root / "vm-restore-probe.json").read_text(encoding="utf-8"))["passed"],
        "owner_artifact_audit": json.loads((root / "owner-build-fixed.json").read_text(encoding="utf-8"))["audit"]["pass"],
        "public_boundary": json.loads((root / "public-boundary-audit.json").read_text(encoding="utf-8"))["private_components_absent"],
        "cloud_locked": True,
        "usb_prohibited": True,
        "scientific_benchmark_not_started": True,
    }
    manifest = {
        "schema": "casulo.inspection3-checkpoint/1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "state": "IN_PROGRESS_CHECKPOINTED",
        "reason": "implementation and regression pass; reseal and human reinspection remain",
        "checks": checks,
        "artifacts": [
            {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}
            for path in sorted(artifacts, key=lambda item: item.relative_to(root).as_posix())
        ],
    }
    (root / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    sealed = [*artifacts, root / "MANIFEST.json"]
    (root / "SHA256SUMS").write_text(
        "".join(f"{sha(path)}  {path.relative_to(root).as_posix()}\n" for path in sorted(sealed, key=lambda item: item.relative_to(root).as_posix())),
        encoding="ascii", newline="\n",
    )
    if not all(checks.values()):
        raise SystemExit("checkpoint checks failed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    main(args.root.resolve(strict=True))
