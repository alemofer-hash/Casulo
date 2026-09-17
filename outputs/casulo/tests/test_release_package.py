from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "casulo_release_package", ROOT / "release/package_release.py"
)
assert SPEC is not None and SPEC.loader is not None
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)


@pytest.mark.parametrize(
    "value",
    ("../escape", "/absolute", "C:/device", "a\\b", "", "a/./b"),
)
def test_release_paths_fail_closed(value: str) -> None:
    with pytest.raises(PACKAGE.ReleasePackageError, match="unsafe release path"):
        PACKAGE._safe_relative(value)


def test_release_path_accepts_canonical_relative_path() -> None:
    assert PACKAGE._safe_relative("docs/spec/TCAP_V1.md").as_posix() == (
        "docs/spec/TCAP_V1.md"
    )


def test_live_hwinfo_csv_is_excluded_from_deterministic_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    live = root / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
    stable = root / "benchmarks/results/stable.json"
    live.parent.mkdir(parents=True)
    stable.parent.mkdir(parents=True, exist_ok=True)
    live.write_text("changing", encoding="utf-8")
    stable.write_text("stable", encoding="utf-8")
    monkeypatch.setattr(PACKAGE, "ROOT", root)
    monkeypatch.setattr(PACKAGE, "INCLUDE_ROOTS", ("benchmarks",))
    monkeypatch.setattr(PACKAGE, "INCLUDE_FILES", ())
    selected = PACKAGE.selected_files()
    assert stable in selected
    assert live not in selected


def test_archive_is_byte_reproducible_and_content_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    release = root / "release"
    release.mkdir(parents=True)
    first = root / "alpha.txt"
    second = root / "nested" / "beta.bin"
    second.parent.mkdir()
    first.write_text("alpha\n", encoding="utf-8")
    second.write_bytes(b"\x00beta\xff")
    archive = release / "package.zip"
    archive_hash = release / "package.zip.sha256"
    monkeypatch.setattr(PACKAGE, "ROOT", root)
    monkeypatch.setattr(PACKAGE, "ARCHIVE", archive)
    monkeypatch.setattr(PACKAGE, "ARCHIVE_HASH", archive_hash)

    result = PACKAGE.write_archive([first, second])
    initial = archive.read_bytes()
    PACKAGE.write_archive([first, second])

    assert archive.read_bytes() == initial
    assert result["status"] == "PASS"
    assert result["two_builds_byte_identical"] is True
    assert result["entries"] == 2


def test_manifest_verifier_rejects_duplicate_and_traversal_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    release = root / "release"
    release.mkdir(parents=True)
    manifest = release / "RELEASE_MANIFEST.json"
    artifact = root / "artifact.bin"
    artifact.write_bytes(b"payload")
    monkeypatch.setattr(PACKAGE, "ROOT", root)
    monkeypatch.setattr(PACKAGE, "MANIFEST", manifest)
    monkeypatch.setattr(PACKAGE, "INCLUDE_ROOTS", ())
    monkeypatch.setattr(PACKAGE, "INCLUDE_FILES", ("artifact.bin",))
    entry = {
        "path": "artifact.bin",
        "bytes": artifact.stat().st_size,
        "sha256": PACKAGE.sha256(artifact),
    }
    document = {
        "schema": "casulo-so-release-manifest/0.2",
        "physical_device_written": False,
        "publication_performed": False,
        "package_tree_sha256": PACKAGE.tree_sha256([artifact]),
        "artifacts": [entry, entry],
    }
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PACKAGE.ReleasePackageError, match="duplicate"):
        PACKAGE.verify_manifest(manifest)

    document["artifacts"] = [{**entry, "path": "../artifact.bin"}]
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PACKAGE.ReleasePackageError, match="unsafe release path"):
        PACKAGE.verify_manifest(manifest)
