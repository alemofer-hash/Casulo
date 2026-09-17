from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/casulo/packages/2026-08-08-full-worker-evidence.zip"
ROOTS = (
    ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2",
    ROOT / "outputs/casulo/energy/2026-08-08-g5-full-worker-hwinfo-energy",
)
FILES = (
    ROOT / "examples/t/flood_surrogate_training.t",
    ROOT / "src/casulo/t/full_work_unit.py",
    ROOT / "src/casulo/t/learn_native.py",
    ROOT / "src/casulo/livelab/energy_v1/full_workers.py",
    ROOT / "tools/run_full_worker_validation.py",
    ROOT / "tools/run_full_worker_energy.py",
    ROOT / "tests/test_t_full_work_unit.py",
    ROOT / "docs/spec/FLOOD_WORK_UNIT_V1.md",
    ROOT / "docs/research/FULL_WORKER_IMPLEMENTATION.md",
    ROOT / "docs/research/WORK_RECEIPT_PROTOCOL.md",
    ROOT / "docs/research/K_LINEARITY_REPORT.md",
    ROOT / "docs/research/THREE_CLOCK_REPORT.md",
    ROOT / "docs/research/FULL_WORKER_EQUIVALENCE.md",
    ROOT / "docs/research/FULL_WORKER_ENERGY_REPORT.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    selected = set(FILES)
    for directory in ROOTS:
        selected.update(item for item in directory.rglob("*") if item.is_file())
    entries = sorted(selected, key=lambda item: item.relative_to(ROOT).as_posix())
    manifest = {
        "schema": "casulo-full-worker-evidence-package/1.0",
        "terminal_state": "BLOCKED_THERMAL_OR_SENSOR",
        "full_worker_state": "PASS_FULL_WORKER_PERFORMANCE_ONLY",
        "files": [
            {"path": item.relative_to(ROOT).as_posix(), "bytes": item.stat().st_size, "sha256": sha256(item)}
            for item in entries
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in entries:
            name = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        info = zipfile.ZipInfo("PACKAGE_MANIFEST.json", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    digest = sha256(OUTPUT)
    OUTPUT.with_suffix(".zip.sha256").write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii", newline="\n")
    print(json.dumps({"package": str(OUTPUT), "sha256": digest, "files": len(entries)}, indent=2))


if __name__ == "__main__":
    main()

