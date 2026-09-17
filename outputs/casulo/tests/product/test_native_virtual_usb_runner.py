from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "os/tools"))

from run_virtual_usb_qemu import build_command


def test_virtual_usb_command_is_read_only_offline_and_argv_based() -> None:
    command = build_command(Path("qemu"), Path("code.fd"), Path("vars.fd"), Path("casulo.img"))
    joined = " ".join(str(item) for item in command)
    assert "qemu-xhci" in joined
    assert "usb-storage" in joined
    assert "readonly=on,file=casulo.img" in joined
    assert "-nic none" in joined
    assert "PhysicalDrive" not in joined
