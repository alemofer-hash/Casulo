#!/usr/bin/env python3
"""Plan and apply a non-destructive Casulo UEFI vendor installation.

The default CLI is inspect/plan only. Applying to a mounted EFI tree requires
an explicit opt-in plus the exact content-bound confirmation phrase. Raw disks,
partitions and the removable-media fallback path are outside this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENDOR = Path("EFI/Teloscorp/Casulo")
SYSTEMD_ENTRY = Path("loader/entries/casulo.conf")
SYSTEMD_CONTENT = (
    "title Casulo OS\n"
    "efi /EFI/Teloscorp/Casulo/CasuloX64.efi\n"
    "sort-key casulo\n"
).encode("utf-8")
GRUB_ENTRY = Path("grub/custom.cfg")
GRUB_CONTENT = (
    "menuentry 'Casulo OS' --class casulo {\n"
    "  insmod chain\n"
    "  search --file --set=casulo_esp /EFI/Teloscorp/Casulo/CasuloX64.efi\n"
    "  chainloader ($casulo_esp)/EFI/Teloscorp/Casulo/CasuloX64.efi\n"
    "}\n"
).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("EFI root must be an existing ordinary directory")
    result: list[Path] = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        if base.is_symlink():
            raise ValueError("symlinked EFI directory refused")
        for name in sorted(files):
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("non-regular EFI entry refused")
            result.append(path.relative_to(root))
        names.sort()
    return sorted(result, key=lambda item: item.as_posix().casefold())


def _tree_files(root: Path) -> dict[str, dict[str, object]]:
    return {
        relative.as_posix(): {
            "bytes": (root / relative).stat().st_size,
            "sha256": _sha_file(root / relative),
        }
        for relative in _relative_files(root)
    }


def _tree_hash(files: dict[str, dict[str, object]]) -> str:
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha_bytes(canonical.encode("utf-8"))


def _grub_sources_custom_cfg(root: Path, existing: dict[str, dict[str, object]]) -> tuple[bool, list[str]]:
    """Prove that an existing GRUB configuration consumes our new drop-in.

    Merely finding a GRUB EFI executable is not enough: hand-written GRUB
    configurations are not required to source ``custom.cfg``.  Inspection is
    bounded and treats unreadable, oversized or non-UTF-8 configurations as no
    proof instead of guessing.
    """

    examined: list[str] = []
    total_bytes = 0
    for relative in sorted(existing, key=str.casefold):
        lowered = relative.casefold()
        if not lowered.endswith("grub.cfg"):
            continue
        metadata = existing[relative]
        size = int(metadata.get("bytes", 0))
        if size < 0 or size > 2 * 1024 * 1024 or total_bytes + size > 4 * 1024 * 1024:
            continue
        path = _confined(root, relative)
        try:
            content = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError):
            continue
        total_bytes += size
        examined.append(relative)
        for line in content.splitlines():
            statement = line.strip().rstrip(";")
            if not statement or statement.startswith("#"):
                continue
            folded = statement.casefold()
            if "custom.cfg" in folded and (
                folded.startswith("source ") or folded.startswith("configfile ")
            ):
                return True, examined
    return False, examined


def inspect_efi_tree(root: Path) -> dict[str, object]:
    resolved = root.resolve(strict=True)
    files = _tree_files(resolved)
    folded = {name.casefold() for name in files}
    managers: list[str] = []
    if "efi/microsoft/boot/bootmgfw.efi" in folded:
        managers.append("windows-boot-manager")
    if any("grub" in name and name.endswith(".efi") for name in folded):
        managers.append("grub")
    if "loader/loader.conf" in folded or any(name.startswith("loader/entries/") for name in folded):
        managers.append("systemd-boot")
    if any("refind" in name and name.endswith(".efi") for name in folded):
        managers.append("refind")
    return {
        "schema": "casulo-efi-inventory/1.0",
        "root": str(resolved),
        "files": files,
        "tree_sha256": _tree_hash(files),
        "boot_managers": managers,
        "fallback_bootx64_present": "efi/boot/bootx64.efi" in folded,
        "read_only_inspection": True,
    }


def _bundle_files(bundle: Path) -> dict[str, dict[str, object]]:
    files = _tree_files(bundle)
    files.pop("BUNDLE_MANIFEST.json", None)
    if not files:
        raise ValueError("empty Casulo EFI bundle")
    required = {
        (VENDOR / "CasuloX64.efi").as_posix(),
        "kernel-x86_64",
        "ramdisk",
    }
    if set(files) != required:
        raise ValueError("incomplete Casulo EFI bundle")
    return files


def make_plan(root: Path, bundle: Path, inventory: dict[str, object] | None = None) -> dict[str, object]:
    resolved_root = root.resolve(strict=True)
    resolved_bundle = bundle.resolve(strict=True)
    observed = inventory or inspect_efi_tree(resolved_root)
    if observed.get("root") != str(resolved_root):
        raise ValueError("inventory root mismatch")
    bundle_files = _bundle_files(resolved_bundle)
    existing = observed["files"]
    assert isinstance(existing, dict)
    existing_folded = {str(relative).casefold(): str(relative) for relative in existing}
    collisions = sorted(
        existing_folded[relative.casefold()]
        for relative in bundle_files
        if relative.casefold() in existing_folded
    )
    generated: dict[str, dict[str, object]] = {}
    managers = list(observed.get("boot_managers", []))
    grub_custom_cfg_consumed = False
    grub_configs_examined: list[str] = []
    if "systemd-boot" in managers:
        systemd_name = SYSTEMD_ENTRY.as_posix()
        if systemd_name.casefold() in existing_folded:
            collisions.append(existing_folded[systemd_name.casefold()])
        else:
            generated[systemd_name] = {
                "bytes": len(SYSTEMD_CONTENT),
                "sha256": _sha_bytes(SYSTEMD_CONTENT),
                "content_utf8": SYSTEMD_CONTENT.decode("utf-8"),
            }
    if "grub" in managers:
        grub_custom_cfg_consumed, grub_configs_examined = _grub_sources_custom_cfg(
            resolved_root, existing
        )
        if grub_custom_cfg_consumed:
            grub_name = GRUB_ENTRY.as_posix()
            if grub_name.casefold() in existing_folded:
                collisions.append(existing_folded[grub_name.casefold()])
            else:
                generated[grub_name] = {
                    "bytes": len(GRUB_CONTENT),
                    "sha256": _sha_bytes(GRUB_CONTENT),
                    "content_utf8": GRUB_CONTENT.decode("utf-8"),
                }
    tree_hash = str(observed["tree_sha256"])
    state = "READY_NON_DESTRUCTIVE" if not collisions else "REFUSED_NAMESPACE_COLLISION"
    return {
        "schema": "casulo-multiboot-plan/1.0",
        "state": state,
        "operation": "COPY_NEW_CASULO_UEFI_FILES_ONLY",
        "target_root": str(resolved_root),
        "target_tree_sha256_before": tree_hash,
        "bundle_root": str(resolved_bundle),
        "bundle_files": bundle_files,
        "generated_files": generated,
        "boot_managers": managers,
        "grub_custom_cfg_consumed": grub_custom_cfg_consumed,
        "grub_configs_examined": grub_configs_examined,
        "overwrites": collisions,
        "deletes": [],
        "modifies_existing_files": False,
        "fallback_boot_path_touched": False,
        "upstream_bootloader_root_abi": ["kernel-x86_64", "ramdisk"],
        "activation": (
            "SYSTEMD_BOOT_NEW_ENTRY"
            if SYSTEMD_ENTRY.as_posix() in generated
            else "GRUB_VERIFIED_CUSTOM_CFG_DROP_IN"
            if GRUB_ENTRY.as_posix() in generated
            else "REFIND_AUTO_DISCOVERY"
            if "refind" in managers
            else "UEFI_FIRMWARE_ENTRY_REQUIRED"
        ),
        "confirmation_phrase": f"INSTALAR CASULO SEM SOBRESCREVER {tree_hash[:16]}",
    }


def _confined(root: Path, relative: str) -> Path:
    candidate = (root / Path(relative)).resolve(strict=False)
    if candidate == root or root not in candidate.parents:
        raise ValueError("path escaped EFI root")
    return candidate


def apply_plan(root: Path, bundle: Path, plan: dict[str, object], *, confirmation: str) -> dict[str, object]:
    resolved_root = root.resolve(strict=True)
    resolved_bundle = bundle.resolve(strict=True)
    if confirmation != plan.get("confirmation_phrase"):
        raise ValueError("confirmation phrase mismatch")
    if plan.get("state") != "READY_NON_DESTRUCTIVE" or plan.get("overwrites"):
        raise ValueError("plan is not eligible for non-destructive apply")
    current = inspect_efi_tree(resolved_root)
    if current["tree_sha256"] != plan.get("target_tree_sha256_before"):
        raise ValueError("EFI tree changed after planning")
    if str(resolved_bundle) != plan.get("bundle_root") or str(resolved_root) != plan.get("target_root"):
        raise ValueError("plan target/bundle mismatch")

    transaction = uuid.uuid4().hex
    stage = resolved_root / "EFI" / "Teloscorp" / f".Casulo-stage-{transaction}"
    final = resolved_root / VENDOR
    if stage.exists() or final.exists():
        raise ValueError("vendor namespace collision")
    created: list[dict[str, object]] = []
    try:
        stage.mkdir(parents=True, exist_ok=False)
        bundle_files = plan["bundle_files"]
        assert isinstance(bundle_files, dict)
        efi_relative = (VENDOR / "CasuloX64.efi").as_posix()
        efi_metadata = bundle_files[efi_relative]
        efi_source = _confined(resolved_bundle, efi_relative)
        staged_efi = stage / "efi.pending"
        shutil.copyfile(efi_source, staged_efi)
        if _sha_file(staged_efi) != efi_metadata["sha256"]:
            raise ValueError("staged EFI hash mismatch")

        staged_roots: list[tuple[str, Path, dict[str, object]]] = []
        for relative in ("kernel-x86_64", "ramdisk"):
            metadata = bundle_files[relative]
            source = _confined(resolved_bundle, relative)
            target = _confined(resolved_root, relative)
            if target.exists():
                raise ValueError("root bootloader ABI collision")
            staged = stage / f"{relative}.pending"
            shutil.copyfile(source, staged)
            if _sha_file(staged) != metadata["sha256"]:
                raise ValueError("staged root bootloader ABI file hash mismatch")
            staged_roots.append((relative, staged, metadata))

        generated_files = plan["generated_files"]
        assert isinstance(generated_files, dict)
        staged_generated: list[tuple[str, Path, dict[str, object]]] = []
        for index, (relative, metadata) in enumerate(generated_files.items()):
            target = _confined(resolved_root, str(relative))
            if target.exists():
                raise ValueError("generated integration collision")
            staged = stage / f"generated-{index}.pending"
            staged.write_text(str(metadata["content_utf8"]), encoding="utf-8", newline="\n")
            if _sha_file(staged) != metadata["sha256"]:
                raise ValueError("staged generated integration hash mismatch")
            staged_generated.append((str(relative), staged, metadata))

        # Publication starts only after every potentially large file has been
        # copied and content-verified.  All renames stay on the same EFI
        # filesystem; no incomplete destination filename is exposed by a
        # recoverable I/O exception.
        final.mkdir(parents=True, exist_ok=False)
        final_efi = final / "CasuloX64.efi"
        staged_efi.rename(final_efi)
        created.append({"path": efi_relative, "sha256": efi_metadata["sha256"]})
        for relative, staged, metadata in staged_roots:
            target = _confined(resolved_root, relative)
            staged.rename(target)
            created.append({"path": relative, "sha256": metadata["sha256"]})
        for relative, staged, metadata in staged_generated:
            target = _confined(resolved_root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.rename(target)
            created.append({"path": relative, "sha256": metadata["sha256"]})
        stage.rmdir()
    except Exception:
        for item in reversed(created):
            target = _confined(resolved_root, str(item["path"]))
            if target.is_file() and not target.is_symlink() and _sha_file(target) == item["sha256"]:
                target.unlink()
        if stage.exists() and stage.is_dir() and not stage.is_symlink():
            for staged in _relative_files(stage):
                candidate = _confined(stage, staged.as_posix())
                candidate.unlink()
            for directory in sorted(
                (path for path in stage.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                directory.rmdir()
            stage.rmdir()
        if final.exists() and final.is_dir() and not final.is_symlink():
            try:
                final.rmdir()
                final.parent.rmdir()
            except OSError:
                pass
        raise

    after = inspect_efi_tree(resolved_root)
    receipt = {
        "schema": "casulo-multiboot-apply-receipt/1.0",
        "state": "APPLIED_NON_DESTRUCTIVE",
        "transaction_id": transaction,
        "target_root": str(resolved_root),
        "tree_sha256_before": current["tree_sha256"],
        "tree_sha256_after": after["tree_sha256"],
        "created": created,
        "overwritten": [],
        "deleted": [],
        "rollback_confirmation_phrase": f"REMOVER SOMENTE CASULO {transaction}",
    }
    return receipt


def rollback(root: Path, receipt: dict[str, object], *, confirmation: str) -> dict[str, object]:
    resolved_root = root.resolve(strict=True)
    if str(resolved_root) != receipt.get("target_root"):
        raise ValueError("rollback target mismatch")
    if confirmation != receipt.get("rollback_confirmation_phrase"):
        raise ValueError("rollback confirmation phrase mismatch")
    created = receipt.get("created")
    if not isinstance(created, list):
        raise ValueError("invalid rollback receipt")
    targets: list[Path] = []
    for item in created:
        if not isinstance(item, dict):
            raise ValueError("invalid rollback entry")
        target = _confined(resolved_root, str(item["path"]))
        if not target.is_file() or target.is_symlink() or _sha_file(target) != item.get("sha256"):
            raise ValueError("rollback refused because a created file changed")
        targets.append(target)
    for target in reversed(targets):
        target.unlink()
    stop = resolved_root / "EFI" / "Teloscorp"
    directories = sorted({target.parent for target in targets}, key=lambda path: len(path.parts), reverse=True)
    for directory in directories:
        current = directory
        while current != resolved_root and resolved_root in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            if current == stop:
                break
            current = current.parent
    return {
        "schema": "casulo-multiboot-rollback-receipt/1.0",
        "state": "ROLLED_BACK_CREATED_FILES_ONLY",
        "transaction_id": receipt.get("transaction_id"),
        "removed": [str(item["path"]) for item in created],
        "overwritten": [],
        "deleted_preexisting": [],
        "tree_sha256_after": inspect_efi_tree(resolved_root)["tree_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo non-destructive UEFI multiboot manager")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--efi-root", type=Path, required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--efi-root", type=Path, required=True)
    plan_parser.add_argument("--bundle", type=Path, required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--efi-root", type=Path, required=True)
    apply_parser.add_argument("--bundle", type=Path, required=True)
    apply_parser.add_argument("--plan", type=Path, required=True)
    apply_parser.add_argument("--confirmation", required=True)
    apply_parser.add_argument("--allow-mounted-efi", action="store_true")
    apply_parser.add_argument("--receipt", type=Path, required=True)
    rollback_parser = sub.add_parser("rollback")
    rollback_parser.add_argument("--efi-root", type=Path, required=True)
    rollback_parser.add_argument("--receipt", type=Path, required=True)
    rollback_parser.add_argument("--confirmation", required=True)
    rollback_parser.add_argument("--allow-mounted-efi", action="store_true")
    rollback_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "inspect":
        result = inspect_efi_tree(args.efi_root)
    elif args.command == "plan":
        result = make_plan(args.efi_root, args.bundle)
        output = args.output.resolve()
        if output.exists():
            raise SystemExit("append-only plan output exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif args.command == "apply":
        if not args.allow_mounted_efi:
            raise SystemExit("apply is fail-closed; pass --allow-mounted-efi after reviewing the plan")
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        result = apply_plan(args.efi_root, args.bundle, plan, confirmation=args.confirmation)
        receipt = args.receipt.resolve()
        if receipt.exists():
            raise SystemExit("append-only receipt output exists")
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        if not args.allow_mounted_efi:
            raise SystemExit("rollback is fail-closed; pass --allow-mounted-efi after reviewing the receipt")
        apply_receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        result = rollback(args.efi_root, apply_receipt, confirmation=args.confirmation)
        output = args.output.resolve()
        if output.exists():
            raise SystemExit("append-only rollback output exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
