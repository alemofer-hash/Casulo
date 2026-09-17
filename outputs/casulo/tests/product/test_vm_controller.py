from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from casulo.product.vm_controller import CasuloVMController, VMControllerError, VMProfile


def files(tmp_path: Path):
    result = []
    for name in ("qemu.exe", "qemu-img.exe", "code.fd", "vars.fd", "base.img"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        result.append(path)
    return result


def test_profile_rejects_physical_devices_and_symlinks(tmp_path) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    with pytest.raises(VMControllerError, match="fisico"):
        VMProfile(qemu, qemu_img, code, variables, Path(r"\\.\PhysicalDrive0"), tmp_path / "state")
    link = tmp_path / "base-link.img"
    try:
        os.symlink(base, link)
    except OSError as error:
        pytest.skip(str(error))
    with pytest.raises(VMControllerError, match="symlink"):
        VMProfile(qemu, qemu_img, code, variables, link, tmp_path / "state")


def test_profile_rejects_windows_junction_and_ads(tmp_path) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    target = tmp_path / "real-state"
    target.mkdir()
    junction = tmp_path / "state-junction"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True, text=True, encoding="cp1252", errors="replace",
        check=False, shell=False,
    )
    if created.returncode != 0:
        pytest.skip("Windows junction creation unavailable: " + created.stderr[-200:])
    assert junction.is_junction()
    with pytest.raises(VMControllerError, match="junction"):
        VMProfile(qemu, qemu_img, code, variables, base, junction)
    ads = Path(str(base) + ":casulo-test")
    ads.write_bytes(b"alternate")
    with pytest.raises(VMControllerError, match="alternate data stream"):
        VMProfile(qemu, qemu_img, code, variables, ads, tmp_path / "state")


def test_qemu_argv_is_array_offline_and_confined(tmp_path) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    (state / "owner-overlay.qcow2").write_bytes(b"overlay")
    (state / "OVMF_VARS.fd").write_bytes(b"vars")
    controller = CasuloVMController(VMProfile(qemu, qemu_img, code, variables, base, state))
    argv = controller.build_argv(acceleration="tcg")
    assert isinstance(argv, list)
    assert "-nic" in argv and argv[argv.index("-nic") + 1] == "none"
    assert not any("PhysicalDrive" in item or "/dev/" in item for item in argv)
    assert "tcp:127.0.0.1:0,server=on,wait=off" in argv
    assert not any("0.0.0.0" in item for item in argv)


def test_snapshot_names_and_resources_are_bounded(tmp_path) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    with pytest.raises(VMControllerError, match="recursos"):
        VMProfile(qemu, qemu_img, code, variables, base, tmp_path / "state", memory_mb=99_999)
    profile = VMProfile(qemu, qemu_img, code, variables, base, tmp_path / "state")
    controller = CasuloVMController(profile)
    with pytest.raises(VMControllerError, match="snapshot"):
        controller.snapshot("../../escape")


def test_restore_rejects_missing_snapshot_before_mutation(tmp_path, monkeypatch) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    (state / "owner-overlay.qcow2").write_bytes(b"overlay")
    controller = CasuloVMController(VMProfile(qemu, qemu_img, code, variables, base, state))
    monkeypatch.setattr(controller, "_capture", lambda _command: "No snapshots available\n")
    mutated: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, "_qemu_img", lambda *args: mutated.append(args))
    with pytest.raises(VMControllerError, match="snapshot inexistente"):
        controller.restore("never-created")
    assert mutated == []


def test_named_snapshots_and_repeated_snapshot_restore_are_idempotent(
    tmp_path, monkeypatch
) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    overlay = state / "owner-overlay.qcow2"
    overlay.write_bytes(b"overlay")
    controller = CasuloVMController(VMProfile(qemu, qemu_img, code, variables, base, state))
    available = ["clean-semantic-multiverse", "guilherme-semantic-live", "named-review"]
    monkeypatch.setattr(controller, "snapshots", lambda: tuple(available))
    mutations: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, "_qemu_img", lambda *args: mutations.append(args))
    for name in available:
        result = controller.snapshot(name)
        assert result["created"] is False and result["idempotent"] is True
    assert len(set(available)) == 3
    first = controller.restore("named-review")
    second = controller.restore("named-review")
    assert first == second
    assert mutations == [
        ("snapshot", "-a", "named-review", str(overlay)),
        ("snapshot", "-a", "named-review", str(overlay)),
    ]


def test_missing_qemu_img_is_wrapped_and_preserves_overlay(tmp_path, monkeypatch) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    overlay = state / "owner-overlay.qcow2"
    overlay.write_bytes(b"unchanged")
    controller = CasuloVMController(VMProfile(qemu, qemu_img, code, variables, base, state))
    before = overlay.read_bytes()
    monkeypatch.setattr(
        "casulo.product.vm_controller.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("gone")),
    )
    with pytest.raises(VMControllerError, match="indisponivel"):
        controller.snapshots()
    assert overlay.read_bytes() == before


def test_bridge_rejects_multiline_or_oversized_payload_before_process(tmp_path) -> None:
    qemu, qemu_img, code, variables, base = files(tmp_path)
    controller = CasuloVMController(
        VMProfile(qemu, qemu_img, code, variables, base, tmp_path / "state")
    )
    with pytest.raises(VMControllerError, match="uma linha"):
        controller.bridge_boot("duas\nlinhas")
    with pytest.raises(VMControllerError, match="uma linha"):
        controller.bridge_boot("x" * 4097)
