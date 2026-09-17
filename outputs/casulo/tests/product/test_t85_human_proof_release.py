from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "release/t85-human-proof"


def load(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_t85_release_is_self_contained_and_verifies() -> None:
    control = load("t85_control_test", ROOT / "tools/human_proof_control.pyw")
    report = control.verify_release(RELEASE)
    assert report["ready"] is True
    assert report["mismatches"] == []
    assert control.repository_root(RELEASE) == (RELEASE / "OWNER_VM/app").resolve()
    manifest = json.loads((RELEASE / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["checkout_dependency"] is False
    assert manifest["pythonpath_dependency"] is False
    assert manifest["state"] == "T85_TECHNICAL_CANDIDATE_PENDING_HUMAN_PROOF"


def test_t85_release_contains_runtime_registry_and_no_private_key() -> None:
    registry = json.loads((RELEASE / "OWNER_VM/CONTENT_REGISTRY.json").read_text(encoding="utf-8"))
    assert registry["t_runtime"]["embedded"] is True
    assert registry["model"]["embedded"] is False
    assert registry["neural_runtime"]["embedded"] is False
    assert not any(path.name in {"owner-ed25519", "public-ed25519", "cloud-standby-ed25519"} for path in RELEASE.rglob("*"))
    assert (RELEASE / "OWNER_VM" / registry["t_runtime"]["relative"]).is_file()


def test_t85_launchers_are_hidden_and_parse() -> None:
    environment = os.environ.copy()
    environment["CASULO_LAUNCHER_DRY_RUN"] = "1"
    launchers = sorted(RELEASE.glob("*.vbs"))
    assert len(launchers) == 4
    for path in launchers:
        raw = path.read_bytes()
        assert not raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe"))
        text = raw.decode("cp1252")
        assert "pyw.exe" in text
        assert "shell.Run command, 0" in text
        assert "powershell" not in text.casefold()
        completed = subprocess.run(["cscript.exe", "//nologo", str(path)], env=environment, capture_output=True, text=True, encoding="cp1252", errors="replace", check=False, shell=False)
        assert completed.returncode == 0
        assert "CASULO_T85_VBS_PARSE_PASS" in completed.stdout


def test_t85_manifest_has_no_developer_absolute_path() -> None:
    manifest = (RELEASE / "MANIFEST.json").read_text(encoding="utf-8")
    assert "C:\\Users\\guimo" not in manifest
    assert "RC12_CANDIDATE_PENDING_GATE" not in manifest
    assert "DEVELOPMENT_NOT_COMMERCIAL" in manifest
