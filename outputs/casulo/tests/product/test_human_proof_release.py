from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "release/human-proof"


def load(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_sealed_human_proof_release_verifies_without_mutating() -> None:
    control = load("human_proof_control_test", ROOT / "tools/human_proof_control.pyw")
    before = control.sha256(RELEASE / "MANIFEST.json")
    report = control.verify_release(RELEASE)
    assert report["ready"] is True
    assert all(report["checks"].values())
    assert report["mismatches"] == []
    assert control.sha256(RELEASE / "MANIFEST.json") == before


def test_release_has_clickable_gui_surface_and_no_powershell_dependency() -> None:
    required = {
        "START_CASULO_OWNER.vbs",
        "VERIFY_RELEASE.vbs",
        "RESTORE_CLEAN_STATE.vbs",
        "COLLECT_FEEDBACK.vbs",
        "HUMAN_PROOF_CARD.md",
        "HUMAN_PROOF_RUNBOOK.md",
        "KNOWN_LIMITATIONS.md",
        "CLAIMS.md",
        "ROLLBACK.md",
        "MANIFEST.json",
        "SBOM.spdx.json",
        "SHA256SUMS",
        "DEVELOPMENT_SIGNATURE.json",
    }
    assert required <= {path.name for path in RELEASE.iterdir()}
    raw_launcher = (RELEASE / "START_CASULO_OWNER.vbs").read_bytes()
    assert not raw_launcher.startswith(b"\xef\xbb\xbf")
    assert not raw_launcher.startswith(b"\xff\xfe")
    launcher = raw_launcher.decode("cp1252")
    assert "OWNER_VM\\tools\\human_proof_window.pyw" in launcher
    assert "powershell" not in launcher.casefold()
    assert "WScript.Shell" in launcher


def test_all_vbs_launchers_parse_in_windows_script_host() -> None:
    environment = os.environ.copy()
    environment["CASULO_LAUNCHER_DRY_RUN"] = "1"
    for launcher in sorted(RELEASE.glob("*.vbs")):
        completed = subprocess.run(
            ["cscript.exe", "//nologo", str(launcher)],
            env=environment,
            capture_output=True,
            text=True,
            encoding="cp1252",
            errors="replace",
            check=False,
            shell=False,
        )
        assert completed.returncode == 0, (launcher.name, completed.stdout, completed.stderr)
        assert "CASULO_VBS_PARSE_PASS" in completed.stdout


def test_feedback_is_selected_text_only_and_outside_overlay(tmp_path) -> None:
    control = load("human_proof_feedback_test", ROOT / "tools/human_proof_control.pyw")
    result = control.collect_feedback(RELEASE, "uma nota selecionada", tmp_path)
    record = json.loads(Path(result["path"]).read_text(encoding="utf-8").splitlines()[0])
    assert record["raw_audio_persisted"] is False
    assert record["full_transcript_persisted"] is False
    assert "owner-vm" not in result["path"]


def test_release_path_is_confined() -> None:
    control = load("human_proof_confinement_test", ROOT / "tools/human_proof_control.pyw")
    with pytest.raises(RuntimeError, match="release/human-proof"):
        control.repository_root(ROOT)
