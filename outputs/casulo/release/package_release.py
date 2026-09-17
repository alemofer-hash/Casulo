from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
MANIFEST = RELEASE / "RELEASE_MANIFEST.json"
ARCHIVE = RELEASE / "casulo-so-rp01-source-and-demo.zip"
ARCHIVE_HASH = ARCHIVE.with_suffix(ARCHIVE.suffix + ".sha256")

REQUIRED = (
    "release/casulo-native-x86_64.img",
    "release/casulo-native-x86_64.img.sha256",
    "release/image-build.json",
    "release/FloodSurrogate.tcap",
    "release/FloodSurrogate.tcap.sha256",
    "release/requirements-rp01.lock",
    "release/TOOLCHAIN_LOCK.json",
    "release/verify_toolchain.py",
    "release/run-qemu.ps1",
    "release/ci_headless.py",
    "release/reproduce.py",
    "release/demo_harness.py",
    "release/preflight_devices.py",
    "release/FLASH_USB_SAFELY.md",
    "docs/EXECUTION_STATE.md",
    "docs/DECISIONS.md",
    "docs/LIMITATIONS.md",
    "docs/REPRODUCIBILITY.md",
    "docs/research/PAPER_GAP_MATRIX.md",
    "docs/research/FINAL_REPORT.md",
    "docs/research/ENERGY_PROTOCOL_V1.md",
    "docs/research/ENERGY_CAPABILITY_MATRIX.md",
    "docs/research/ENERGY_FINAL_REPORT.md",
    "docs/spec/TCAP_V1.md",
    "docs/spec/SYSCALL_ABI_V1.md",
    "docs/spec/SEMANTIC_SCHEDULER_V1.md",
    "docs/demo/DEMO_RUNBOOK.md",
    "examples/t/flood_surrogate_training.t",
    "evidence/casulo-os-rp01/g0/baseline.json",
    "evidence/casulo-os-rp01/g1/qemu-boot-100.json",
    "evidence/casulo-os-rp01/g2/qemu-g2-full-5.json",
    "evidence/casulo-os-rp01/g2/platform-probes/qemu-platform-probes.json",
    "evidence/casulo-os-rp01/g3/qemu-tcap-ring3-3.json",
    "evidence/casulo-os-rp01/g4/kernel/qemu-g4-kernel-5.json",
    "evidence/casulo-os-rp01/g6/qemu-virtual-usb-10.json",
    "evidence/casulo-os-rp01/g7/demo-rehearsal-10.json",
    "os/kernel/src/shell.rs",
    "os/kernel/src/platform.rs",
    "SECURITY.md",
)

INCLUDE_ROOTS = (
    "os",
    "src",
    "tests",
    "livelab",
    "tools",
    "docs",
    "release",
    "examples",
    "evidence/casulo-os-rp01",
    "benchmarks",
    "energy",
)

INCLUDE_FILES = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "NOTICE.md",
    "CITATION.cff",
    "SECURITY.md",
)

EXCLUDED_PARTS = {
    ".git",
    ".hypothesis",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    ".tmp-livelab",
    ".tmp-tests",
    "__pycache__",
    "target",
}

# A logger-owned append-only source cannot be part of a deterministic archive:
# it may change between manifest hashing and ZIP creation. Campaigns preserve
# bounded snapshots, extracted immutable segments and source hashes instead.
EXCLUDED_RELATIVE_PATHS = {
    "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV",
}

EXTRACTED_SMOKE_TESTS = (
    "tests/test_t_tcap.py",
    "tests/test_demo_harness.py",
    "tests/test_os_qemu_safety.py",
)


class ReleasePackageError(RuntimeError):
    """The local release package is incomplete, unsafe, or irreproducible."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    raw_parts = value.split("/")
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or (path.parts and ":" in path.parts[0])
    ):
        raise ReleasePackageError(f"unsafe release path: {value!r}")
    return path


def repository_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def repository_dirty() -> bool | None:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip())


def selected_files() -> list[Path]:
    files: set[Path] = set()
    for relative in INCLUDE_FILES:
        path = ROOT / relative
        if path.is_file() and not path.is_symlink():
            files.add(path)
    for relative in INCLUDE_ROOTS:
        root = ROOT / relative
        if not root.is_dir() or root.is_symlink():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(ROOT)
            if rel.as_posix() in EXCLUDED_RELATIVE_PATHS:
                continue
            if any(part in EXCLUDED_PARTS or part.startswith(".tmp-") for part in rel.parts):
                continue
            if path in {ARCHIVE, ARCHIVE_HASH}:
                continue
            files.add(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def tree_sha256(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "little"))
        digest.update(content)
    return digest.hexdigest()


def _artifact_entries(files: list[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in files
        if path != MANIFEST
    ]


def write_manifest(files: list[Path]) -> dict[str, Any]:
    artifacts = _artifact_entries(files)
    package_tree = [path for path in files if path != MANIFEST]
    commit = repository_commit()
    dirty = repository_dirty()
    tree_hash = tree_sha256(package_tree)
    state_id = (
        f"{commit}+dirty-tree-{tree_hash}"
        if commit and dirty is not False
        else commit or f"uncommitted-source+tree-{tree_hash}"
    )
    manifest = {
        "schema": "casulo-so-release-manifest/0.2",
        "release": "Casulo SO Research Preview 0.1",
        "repository_commit": commit,
        "repository_dirty": dirty,
        "repository_state_id": state_id,
        "package_tree_sha256": tree_hash,
        "physical_device_written": False,
        "publication_performed": False,
        "energy": {
            "status": "BLOCKED_HWINFO_POLLING_NOT_CHANGED",
            "joules": None,
            "campaign": "energy/2026-08-07-g5-hwinfo-thermal-recovery",
            "physical_measurement_performed": False,
            "live_source_excluded_from_archive": "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV",
            "immutable_source_segment_included": "energy/2026-08-07-g5-hwinfo-thermal-recovery/source_segment.csv",
        },
        "artifacts": artifacts,
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def verify_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReleasePackageError("release manifest is absent or not a regular file")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleasePackageError(f"invalid release manifest: {exc}") from exc
    if manifest.get("schema") != "casulo-so-release-manifest/0.2":
        raise ReleasePackageError("unexpected release manifest schema")
    if manifest.get("physical_device_written") is not False:
        raise ReleasePackageError("physical_device_written must be false")
    if manifest.get("publication_performed") is not False:
        raise ReleasePackageError("publication_performed must be false")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise ReleasePackageError("release manifest has no artifact entries")
    observed: set[str] = set()
    expected_files = [item for item in selected_files() if item != MANIFEST]
    expected_paths = {item.relative_to(ROOT).as_posix() for item in expected_files}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ReleasePackageError("malformed release artifact entry")
        relative = _safe_relative(str(entry["path"]))
        relative_text = relative.as_posix()
        if relative_text in observed:
            raise ReleasePackageError(f"duplicate release artifact: {relative_text}")
        observed.add(relative_text)
        artifact = ROOT.joinpath(*relative.parts)
        if not artifact.is_file() or artifact.is_symlink():
            raise ReleasePackageError(f"missing regular release artifact: {relative_text}")
        if type(entry["bytes"]) is not int or entry["bytes"] != artifact.stat().st_size:
            raise ReleasePackageError(f"release artifact size mismatch: {relative_text}")
        if entry["sha256"] != sha256(artifact):
            raise ReleasePackageError(f"release artifact hash mismatch: {relative_text}")
    if observed != expected_paths:
        missing = sorted(expected_paths - observed)
        unexpected = sorted(observed - expected_paths)
        raise ReleasePackageError(
            f"manifest file-set mismatch: missing={missing}, unexpected={unexpected}"
        )
    actual_tree = tree_sha256(expected_files)
    if manifest.get("package_tree_sha256") != actual_tree:
        raise ReleasePackageError("package tree hash mismatch")
    return {
        "status": "PASS",
        "artifacts": len(entries),
        "package_tree_sha256": actual_tree,
        "manifest_sha256": sha256(path),
    }


def _write_archive_to(destination: Path, files: list[Path]) -> None:
    stable_time = (2026, 8, 7, 0, 0, 0)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            _safe_relative(relative)
            info = zipfile.ZipInfo(relative, stable_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def verify_archive(archive_path: Path, files: list[Path]) -> dict[str, Any]:
    expected = {path.relative_to(ROOT).as_posix(): path for path in files}
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ReleasePackageError("archive contains duplicate paths")
        for name in names:
            _safe_relative(name)
        if set(names) != set(expected):
            raise ReleasePackageError("archive file set differs from selected release files")
        for info in infos:
            if archive.read(info) != expected[info.filename].read_bytes():
                raise ReleasePackageError(f"archive content mismatch: {info.filename}")
    return {
        "status": "PASS",
        "entries": len(expected),
        "archive_sha256": sha256(archive_path),
    }


def write_archive(files: list[Path]) -> dict[str, Any]:
    _write_archive_to(ARCHIVE, files)
    with tempfile.TemporaryDirectory(prefix="casulo-release-repro-") as temporary:
        second = Path(temporary) / ARCHIVE.name
        _write_archive_to(second, files)
        if ARCHIVE.read_bytes() != second.read_bytes():
            raise ReleasePackageError("two consecutive release archives are not byte-identical")
    result = verify_archive(ARCHIVE, files)
    ARCHIVE_HASH.write_text(
        f"{result['archive_sha256']}  {ARCHIVE.name}\n",
        encoding="ascii",
        newline="\n",
    )
    result["two_builds_byte_identical"] = True
    return result


def extracted_smoke_test(archive_path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="casulo-release-extract-") as temporary:
        extracted = Path(temporary) / "casulo-so-rp01"
        extracted.mkdir()
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info in archive.infolist():
                relative = _safe_relative(info.filename)
                destination = extracted.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(info))
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(extracted / "src")
        local_temp = extracted / ".tmp"
        local_temp.mkdir()
        (extracted / ".tmp-tests").mkdir()
        environment["TMP"] = str(local_temp)
        environment["TEMP"] = str(local_temp)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--basetemp",
                ".tmp-tests/extracted-release",
                *EXTRACTED_SMOKE_TESTS,
            ],
            cwd=extracted,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise ReleasePackageError(
                "extracted archive smoke tests failed:\n" + completed.stdout[-4000:]
            )
        return {
            "status": "PASS",
            "tests": list(EXTRACTED_SMOKE_TESTS),
            "output": completed.stdout.strip(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create and verify a deterministic local Casulo SO release package."
    )
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--skip-extracted-tests", action="store_true")
    args = parser.parse_args()
    missing = [relative for relative in REQUIRED if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit("missing required release files:\n" + "\n".join(missing))
    files_before_manifest = selected_files()
    write_manifest(files_before_manifest)
    manifest_result = verify_manifest()
    files = selected_files()
    archive_result = None
    extracted_result = None
    if not args.verify_only:
        archive_result = write_archive(files)
        if not args.skip_extracted_tests:
            extracted_result = extracted_smoke_test(ARCHIVE)
    print(
        json.dumps(
            {
                "schema": "casulo-so-release-package/0.2",
                "required_files": len(REQUIRED),
                "selected_files": len(files),
                "manifest": manifest_result,
                "archive": archive_result,
                "extracted_smoke": extracted_result,
                "physical_device_written": False,
                "publication_performed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
