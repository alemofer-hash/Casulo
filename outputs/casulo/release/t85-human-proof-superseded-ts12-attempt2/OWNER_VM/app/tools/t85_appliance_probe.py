from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load_control(path: Path):
    loader = SourceFileLoader("t85_sealed_control", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("controle T85 nao pode ser carregado")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release, output = args.release.resolve(strict=True), args.output.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output exists; overwrite denied")
    app = release / "OWNER_VM/app"
    if not app.is_dir():
        raise SystemExit("bundled application missing")
    if os.environ.get("PYTHONPATH"):
        raise SystemExit("PYTHONPATH must be absent for the sealed-appliance probe")
    sys.path[:0] = [str(app), str(app / "src"), str(app / "private/casulo-owner/src")]
    control = load_control(app / "tools/human_proof_control.pyw")
    verification = control.verify_release(release)
    if not verification["ready"]:
        raise SystemExit("sealed verifier rejected release")

    from casulo.product.vm_controller import VMControllerError

    state = output / "owner-state"
    controller = control.controller_for_release(release)
    # The sealed controller uses LOCALAPPDATA.  For this isolated evidence
    # process the caller sets LOCALAPPDATA to a fresh directory.
    if not str(controller.overlay_path).startswith(str(Path(os.environ["LOCALAPPDATA"]).resolve())):
        raise SystemExit("state escaped isolated LOCALAPPDATA")
    output.mkdir(parents=True)
    base = release / "OWNER_VM/casulo-native-generative-interactive.img"
    base_before = sha256(base)
    missing_restore: dict[str, Any] | None = None
    try:
        controller.restore("t85-never-created")
    except VMControllerError as error:
        missing_restore = {"recoverable": True, "message": str(error), "overlay_preserved": controller.overlay_path.is_file()}
    clean = controller.snapshot("t85-human-proof-clean")
    cycles = [controller.bridge_boot(f"t85-appliance-cycle-{index}", acceleration="tcg", timeout=60) for index in range(1, 4)]
    live = controller.snapshot("t85-owner-live")
    restored = controller.restore("t85-owner-live")
    crash = controller.crash_recovery_probe()
    base_after = sha256(base)

    launcher_results = []
    environment = os.environ.copy()
    environment["CASULO_LAUNCHER_DRY_RUN"] = "1"
    for launcher in sorted(release.glob("*.vbs")):
        completed = subprocess.run(
            ["cscript.exe", "//nologo", str(launcher)], env=environment,
            capture_output=True, text=True, encoding="cp1252", errors="replace",
            check=False, shell=False,
        )
        launcher_results.append({"name": launcher.name, "returncode": completed.returncode, "parse_marker": "CASULO_T85_VBS_PARSE_PASS" in completed.stdout})

    checks = {
        "sealed_verifier": verification["ready"] is True,
        "no_checkout": control.repository_root(release) == app.resolve(),
        "no_pythonpath": "PYTHONPATH" not in os.environ,
        "missing_restore_recoverable": bool(missing_restore and missing_restore["recoverable"]),
        "three_clean_cycles": len(cycles) == 3 and all(item["passed"] for item in cycles),
        "base_immutable": base_before == base_after and all(item["base_unchanged"] for item in cycles),
        "network_denied": all(item["network"] == "denied" for item in cycles),
        "block_devices_absent": all(item["host_block_devices"] is False for item in cycles),
        "snapshot_restore": clean["snapshot"] == "t85-human-proof-clean" and live["snapshot"] == restored["restored"],
        "crash_recovery": crash["process_terminated"] and crash["overlay_check_returncode"] == 0 and crash["base_unchanged"],
        "launchers_parse": len(launcher_results) == 4 and all(item["returncode"] == 0 and item["parse_marker"] for item in launcher_results),
        "common_flow_no_terminal": all("pyw.exe" in path.read_text(encoding="cp1252") and "shell.Run command, 0" in path.read_text(encoding="cp1252") for path in release.glob("*.vbs")),
    }
    report = {
        "schema": "casulo.t85-appliance-probe/1.0",
        "gate": "TS12_APPLIANCE_PASS" if all(checks.values()) else "TS12_APPLIANCE_FAIL",
        "checks": checks,
        "release_manifest_sha256": sha256(release / "MANIFEST.json"),
        "verification": verification,
        "missing_restore": missing_restore,
        "clean_snapshot": clean,
        "live_snapshot": live,
        "restore": restored,
        "cycles": cycles,
        "crash": crash,
        "launchers": launcher_results,
        "base_sha256_before": base_before,
        "base_sha256_after": base_after,
        "state_root": str(controller.overlay_path.parent),
        "state_root_is_external_to_release": not controller.overlay_path.is_relative_to(release),
        "checkout_dependency": False,
        "pythonpath_dependency": False,
        "locks": {"cloud": "RELEASE_LOCKED", "guest_network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
    }
    write_json(output / "t85-appliance-probe.json", report)
    print(json.dumps({"gate": report["gate"], "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if report["gate"] == "TS12_APPLIANCE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
