from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


TOOLS = Path(__file__).resolve().parents[1] / "os" / "tools"
SPEC = importlib.util.spec_from_file_location("casulo_run_qemu_safety", TOOLS / "run_qemu.py")
assert SPEC is not None and SPEC.loader is not None
RUN_QEMU = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_QEMU)


@pytest.mark.parametrize(
    "device",
    [r"\\.\PhysicalDrive0", r"\\?\GLOBALROOT\Device\Harddisk0", "/dev/sda"],
)
def test_device_paths_are_refused_before_resolution(device: str) -> None:
    with pytest.raises(ValueError, match="device path refused"):
        RUN_QEMU.safe_regular_workspace_file(Path(device))


def test_only_regular_files_below_workspace_are_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    inside = repository / "image.img"
    inside.write_bytes(b"regular-image")
    outside = tmp_path / "outside.img"
    outside.write_bytes(b"outside")
    monkeypatch.setattr(RUN_QEMU, "ROOT", repository)

    assert RUN_QEMU.safe_regular_workspace_file(inside) == inside.resolve()
    with pytest.raises(ValueError, match="regular workspace file"):
        RUN_QEMU.safe_regular_workspace_file(outside)


def test_symbolic_link_image_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    target = repository / "target.img"
    target.write_bytes(b"target")
    link = repository / "link.img"
    try:
        os.symlink(target, link)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.setattr(RUN_QEMU, "ROOT", repository)

    with pytest.raises(ValueError, match="symbolic-link image refused"):
        RUN_QEMU.safe_regular_workspace_file(link)
