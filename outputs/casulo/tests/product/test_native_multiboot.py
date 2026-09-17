from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.casulo_multiboot import apply_plan, inspect_efi_tree, make_plan, rollback


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic_efi(root: Path, manager: str) -> dict[str, str]:
    fixtures = {
        "EFI/Microsoft/Boot/bootmgfw.efi": b"windows-manager",
        "EFI/BOOT/BOOTX64.EFI": b"existing-fallback",
        "keep/user-file.bin": b"must-survive",
    }
    if manager == "grub":
        fixtures["EFI/arch/grubx64.efi"] = b"grub"
        fixtures["grub/grub.cfg"] = b"menuentry 'Arch' {}\nsource $prefix/custom.cfg\n"
    elif manager == "systemd-boot":
        fixtures["loader/loader.conf"] = b"default arch.conf\n"
        fixtures["loader/entries/arch.conf"] = b"title Arch Linux\n"
    elif manager == "refind":
        fixtures["EFI/refind/refind_x64.efi"] = b"refind"
        fixtures["EFI/refind/refind.conf"] = b"timeout 20\n"
    for relative, content in fixtures.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {relative: _sha(root / relative) for relative in fixtures}


@pytest.mark.parametrize("manager", ["windows", "grub", "systemd-boot", "refind"])
def test_multiboot_install_preserves_every_preexisting_byte(tmp_path: Path, manager: str) -> None:
    efi = tmp_path / "esp"
    before = _synthetic_efi(efi, manager)
    bundle = tmp_path / "bundle"
    (bundle / "EFI/Teloscorp/Casulo").mkdir(parents=True)
    (bundle / "EFI/Teloscorp/Casulo/CasuloX64.efi").write_bytes(b"casulo-efi")
    (bundle / "kernel-x86_64").write_bytes(b"kernel")
    (bundle / "ramdisk").write_bytes(b"pack")

    inventory = inspect_efi_tree(efi)
    plan = make_plan(efi, bundle, inventory)
    assert plan["operation"] == "COPY_NEW_CASULO_UEFI_FILES_ONLY"
    assert plan["overwrites"] == []
    receipt = apply_plan(efi, bundle, plan, confirmation=plan["confirmation_phrase"])

    assert receipt["state"] == "APPLIED_NON_DESTRUCTIVE"
    assert all(_sha(efi / relative) == digest for relative, digest in before.items())
    assert (efi / "EFI/Teloscorp/Casulo/CasuloX64.efi").read_bytes() == b"casulo-efi"
    assert (efi / "kernel-x86_64").read_bytes() == b"kernel"
    assert (efi / "ramdisk").read_bytes() == b"pack"
    if manager == "grub":
        assert plan["activation"] == "GRUB_VERIFIED_CUSTOM_CFG_DROP_IN"
        assert "chainloader" in (efi / "grub/custom.cfg").read_text(encoding="utf-8")
    if manager == "systemd-boot":
        assert "CasuloX64.efi" in (efi / "loader/entries/casulo.conf").read_text(encoding="utf-8")
    rollback(efi, receipt, confirmation=receipt["rollback_confirmation_phrase"])
    assert all(_sha(efi / relative) == digest for relative, digest in before.items())
    assert not (efi / "EFI/Teloscorp/Casulo").exists()


def test_multiboot_refuses_collision_and_wrong_confirmation(tmp_path: Path) -> None:
    efi = tmp_path / "esp"
    _synthetic_efi(efi, "windows")
    bundle = tmp_path / "bundle"
    target = bundle / "EFI/Teloscorp/Casulo/CasuloX64.efi"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new")
    (bundle / "kernel-x86_64").write_bytes(b"kernel")
    (bundle / "ramdisk").write_bytes(b"pack")
    collision = efi / "EFI/Teloscorp/Casulo/CasuloX64.efi"
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"old")
    plan = make_plan(efi, bundle, inspect_efi_tree(efi))
    assert plan["state"] == "REFUSED_NAMESPACE_COLLISION"
    with pytest.raises(ValueError, match="confirmation"):
        apply_plan(efi, bundle, plan, confirmation="wrong")


def test_grub_without_verified_custom_cfg_source_does_not_claim_activation(tmp_path: Path) -> None:
    efi = tmp_path / "esp"
    _synthetic_efi(efi, "grub")
    (efi / "grub/grub.cfg").write_bytes(b"menuentry 'Arch' {}\n# source custom.cfg\n")
    bundle = tmp_path / "bundle"
    target = bundle / "EFI/Teloscorp/Casulo/CasuloX64.efi"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new")
    (bundle / "kernel-x86_64").write_bytes(b"kernel")
    (bundle / "ramdisk").write_bytes(b"pack")

    plan = make_plan(efi, bundle)

    assert plan["state"] == "READY_NON_DESTRUCTIVE"
    assert plan["activation"] == "UEFI_FIRMWARE_ENTRY_REQUIRED"
    assert plan["grub_custom_cfg_consumed"] is False
    assert "grub/custom.cfg" not in plan["generated_files"]


def test_multiboot_module_contains_no_raw_disk_or_fallback_overwrite() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/casulo_multiboot.py").read_text(encoding="utf-8")
    for forbidden in ("PhysicalDrive", "Clear-Disk", "Format-Volume", "diskpart"):
        assert forbidden not in source
    assert "EFI/Teloscorp/Casulo" in source


def test_multiboot_cli_apply_and_rollback_are_receipt_bound(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    cli = root / "tools/casulo_multiboot.py"
    efi = tmp_path / "esp"
    before = _synthetic_efi(efi, "systemd-boot")
    bundle = tmp_path / "bundle"
    target = bundle / "EFI/Teloscorp/Casulo/CasuloX64.efi"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"casulo")
    (bundle / "kernel-x86_64").write_bytes(b"kernel")
    (bundle / "ramdisk").write_bytes(b"pack")
    plan_path = tmp_path / "plan.json"
    apply_receipt = tmp_path / "apply.json"
    rollback_receipt = tmp_path / "rollback.json"

    subprocess.run(
        [sys.executable, str(cli), "plan", "--efi-root", str(efi), "--bundle", str(bundle), "--output", str(plan_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    subprocess.run(
        [
            sys.executable, str(cli), "apply", "--efi-root", str(efi), "--bundle", str(bundle),
            "--plan", str(plan_path), "--confirmation", plan["confirmation_phrase"],
            "--allow-mounted-efi", "--receipt", str(apply_receipt),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(apply_receipt.read_text(encoding="utf-8"))
    subprocess.run(
        [
            sys.executable, str(cli), "rollback", "--efi-root", str(efi),
            "--receipt", str(apply_receipt), "--confirmation", receipt["rollback_confirmation_phrase"],
            "--allow-mounted-efi", "--output", str(rollback_receipt),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    rolled_back = json.loads(rollback_receipt.read_text(encoding="utf-8"))
    assert rolled_back["state"] == "ROLLED_BACK_CREATED_FILES_ONLY"
    assert all(_sha(efi / relative) == digest for relative, digest in before.items())
