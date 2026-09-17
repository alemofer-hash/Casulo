#!/usr/bin/env python3
"""Create append-only evidence for Casulo coexistence and exact rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.casulo_multiboot import apply_plan, inspect_efi_tree, make_plan, rollback  # noqa: E402


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _fixtures(root: Path, scenario: str) -> None:
    _write(root / "EFI/Microsoft/Boot/bootmgfw.efi", b"synthetic-windows-manager")
    _write(root / "EFI/BOOT/BOOTX64.EFI", b"synthetic-existing-fallback")
    _write(root / "ARCH_LINUX_MUST_SURVIVE.txt", b"synthetic-arch-state")
    if scenario == "grub":
        _write(root / "EFI/arch/grubx64.efi", b"synthetic-grub")
        _write(
            root / "grub/grub.cfg",
            b"menuentry 'Arch Linux' {}\nsource $prefix/custom.cfg\n",
        )
    elif scenario == "systemd-boot":
        _write(root / "loader/loader.conf", b"default arch.conf\n")
        _write(root / "loader/entries/arch.conf", b"title Arch Linux\n")
    elif scenario == "refind":
        _write(root / "EFI/refind/refind_x64.efi", b"synthetic-refind")
        _write(root / "EFI/refind/refind.conf", b"timeout 20\n")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Casulo non-destructive multiboot")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    output = args.output.resolve()
    if ROOT.resolve() not in bundle.parents or ROOT.resolve() not in output.parents or output.exists():
        raise SystemExit("bundle/output confinement or append-only gate failed")
    output.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    for scenario in ("windows", "grub", "systemd-boot", "refind"):
        case_root = output / scenario
        esp = case_root / "esp"
        _fixtures(esp, scenario)
        before = inspect_efi_tree(esp)
        plan = make_plan(esp, bundle, before)
        receipt = apply_plan(esp, bundle, plan, confirmation=str(plan["confirmation_phrase"]))
        after = inspect_efi_tree(esp)
        before_files = before["files"]
        after_files = after["files"]
        assert isinstance(before_files, dict) and isinstance(after_files, dict)
        preserved = all(after_files.get(name) == metadata for name, metadata in before_files.items())
        rollback_receipt = rollback(
            esp,
            receipt,
            confirmation=str(receipt["rollback_confirmation_phrase"]),
        )
        restored = inspect_efi_tree(esp)
        exact_rollback = restored["tree_sha256"] == before["tree_sha256"]
        for name, payload in (
            ("inventory-before.json", before),
            ("plan.json", plan),
            ("apply-receipt.json", receipt),
            ("inventory-after.json", after),
            ("rollback-receipt.json", rollback_receipt),
            ("inventory-restored.json", restored),
        ):
            (case_root / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        cases.append({
            "scenario": scenario,
            "boot_managers": before["boot_managers"],
            "plan_state": plan["state"],
            "activation": plan["activation"],
            "preexisting_bytes_preserved": preserved,
            "exact_tree_restored": exact_rollback,
            "fallback_unchanged": (
                before_files["EFI/BOOT/BOOTX64.EFI"] == after_files["EFI/BOOT/BOOTX64.EFI"]
            ),
            "passed": preserved and exact_rollback and receipt["overwritten"] == [] and receipt["deleted"] == [],
        })
    report = {
        "schema": "casulo-multiboot-coexistence-validation/1.0",
        "state": "CASULO_MULTIBOOT_NON_DESTRUCTIVE_VALIDATED",
        "bundle": bundle.relative_to(ROOT).as_posix(),
        "bundle_manifest_sha256": _sha(bundle / "BUNDLE_MANIFEST.json"),
        "cases": cases,
        "physical_device_written": False,
        "raw_image_written_to_device": False,
        "passed": all(case["passed"] for case in cases),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
