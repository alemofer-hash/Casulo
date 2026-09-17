from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LAUNCHER = ROOT / "os/tools/launch_native_creation_visible.py"
POWERSHELL_LAUNCHER = ROOT / "release/CASULO_NATIVE_BOOT_TO_CREATION_PROOF.ps1"
VBS_LAUNCHER = ROOT / "release/START_CASULO_NATIVE_CREATION_PROOF.vbs"


def test_visible_launcher_is_bounded_and_has_no_shell_or_network() -> None:
    source = PYTHON_LAUNCHER.read_text(encoding="utf-8")
    command_source = (ROOT / "os/tools/run_native_model_paged_qemu.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "build_command" in source
    assert '"-nic"' in command_source and '"none"' in command_source
    assert "readonly=on" in command_source
    assert "shell=False" in source
    assert "SEALED_IMAGE_SHA256" in source
    assert "MODEL_SHA256" in source
    assert "PhysicalDrive" not in source
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"system", "popen"}
        for node in ast.walk(tree)
    )


def test_human_launchers_reference_only_the_bounded_launcher() -> None:
    powershell = POWERSHELL_LAUNCHER.read_text(encoding="utf-8")
    vbs = VBS_LAUNCHER.read_text(encoding="ascii")
    assert "launch_native_creation_visible.py" in powershell
    assert "casulo-native-neural-port-np10-attempt-5.img" in powershell
    assert "CASULO_NATIVE_BOOT_TO_CREATION_PROOF.ps1" in vbs
    assert "PhysicalDrive" not in powershell + vbs
    assert "http://" not in powershell + vbs and "https://" not in powershell + vbs


def test_vbs_is_ascii_and_bom_free() -> None:
    raw = VBS_LAUNCHER.read_bytes()
    assert not raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"))
    raw.decode("ascii")
