from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "os/tools"))

from casulo.t.v2_tcap import build_native_probe_bundle  # noqa: E402
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, boot_once, sha256  # noqa: E402


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def marker(serial: str, name: str) -> str:
    prefix = name + "="
    values = [line[len(prefix):] for line in serial.splitlines() if line.startswith(prefix)]
    if len(values) != 1:
        raise RuntimeError(f"expected one {name}, observed {len(values)}")
    return values[0]


def logical(receipt: dict) -> dict:
    return {key: value for key, value in receipt.items() if key not in {"runtime_id", "monotonic_timestamp_ns", "receipt_hash"}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthesis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=35.0)
    args = parser.parse_args()
    synthesis = args.synthesis.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or synthesis not in output.parents:
        raise SystemExit("output must be new and nested under synthesis evidence")
    output.mkdir(parents=True)
    runtime = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
    dependencies = (Path(DEFAULT_QEMU), Path(DEFAULT_CODE), Path(DEFAULT_VARS))
    if any(not item.is_file() for item in (*dependencies, runtime)):
        raise SystemExit("Native/QEMU/runtime dependency missing")
    reports: list[dict] = []
    for index, agent_root in enumerate(sorted((synthesis / "agents").iterdir()), start=1):
        if not agent_root.is_dir():
            continue
        plan = json.loads((agent_root / "architecture-plan.json").read_text(encoding="utf-8"))
        tcap = agent_root / "agent.tcap"
        policy = f"owner.agent.{plan['agent_id']}.{plan['module_suffixes'][0]}"
        payload = {
            "confirmed": True,
            "project_match": True,
            "evidence_statuses": ["PASS"] * 3,
            **{item["field_name"]: True for item in plan["constraints"]},
            "cancelled": False,
        }
        case_dir = output / f"case-{index:02d}-{plan['case_id']}"
        case_dir.mkdir()
        input_path = case_dir / "input.json"
        dump(input_path, payload)
        productive_run = subprocess.run(
            [str(runtime), str(tcap), f"{policy}::decide", str(input_path), "", "agent_behavior", f"agent:{plan['case_id']}", "0" * 64],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
        )
        if productive_run.returncode != 0:
            raise SystemExit(f"productive runtime failed: {productive_run.stderr}")
        productive = json.loads(productive_run.stdout)
        bundle = build_native_probe_bundle(
            tcap, case_dir / "native-probe.json", function_name="decide", payload=payload,
            grants=(), surface_id="agent_behavior", scope_id=f"agent:{plan['case_id']}",
        )
        environment = os.environ.copy()
        environment["CASULO_TCAP_RAMDISK"] = str(bundle)
        built = subprocess.run(
            ["cargo", "+nightly-2026-02-01", "-Z", "bindeps", "build", "--manifest-path", "os/Cargo.toml", "--release", "--locked", "--offline"],
            cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False,
        )
        if built.returncode != 0:
            raise SystemExit(f"Native build failed: {built.stdout}\n{built.stderr}")
        launcher = ROOT / "os/target/release" / ("casulo-os-image.exe" if os.name == "nt" else "casulo-os-image")
        image_run = subprocess.run([str(launcher)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15, check=True)
        image = Path(image_run.stdout.strip()).resolve(strict=True)
        boot = boot_once(image, *dependencies, args.timeout)
        serial = str(boot["serial"])
        native_observable = json.loads(marker(serial, "TCAP_V2_OBSERVABLE"))
        native_receipt = json.loads(marker(serial, "TCAP_V2_RECEIPT"))
        checks = {
            "qemu_success": boot["returncode"] == 33 and boot["timed_out"] is False,
            "native_gate": "TCAP_V2_GATE=PASS" in serial,
            "isolated": "TCAP_V2_ISOLATION=qemu-guest-no-network-no-host-block-device" in serial,
            "observable_equal": native_observable == productive["observable"],
            "receipt_equal": logical(native_receipt) == logical(productive["runtime_receipt"]),
            "runtime_ids_distinct": {native_receipt["runtime_id"], productive["runtime_receipt"]["runtime_id"]} == {"t-runtime/native-2.0", "t-runtime/rust-2.0"},
        }
        (case_dir / "serial.log").write_text(serial, encoding="utf-8", newline="\n")
        dump(case_dir / "case.json", {
            "case_id": plan["case_id"], "agent_id": plan["agent_id"], "checks": checks,
            "productive": productive, "native_observable": native_observable,
            "native_receipt": native_receipt, "bundle_sha256": sha256(bundle),
            "image_sha256": sha256(image), "serial_sha256": hashlib.sha256(serial.encode("utf-8")).hexdigest(),
        })
        reports.append({"case_id": plan["case_id"], "agent_id": plan["agent_id"], "checks": checks})

    # Restore the normal v1 image so this gate cannot silently alter RC13.
    environment = os.environ.copy()
    environment.pop("CASULO_TCAP_RAMDISK", None)
    restored = subprocess.run(
        ["cargo", "+nightly-2026-02-01", "-Z", "bindeps", "build", "--manifest-path", "os/Cargo.toml", "--release", "--locked", "--offline"],
        cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False,
    )
    checks = {
        "three_agents": len(reports) == 3,
        "all_conformant": all(all(item["checks"].values()) for item in reports),
        "default_v1_restored": restored.returncode == 0,
    }
    gate = {
        "schema": "casulo.t85.native-holdout-conformance/1.0",
        "gate": "TS7_T_NONTRIVIAL_HOLDOUTS_NATIVE_PASS" if all(checks.values()) else "TS7_NATIVE_FAIL",
        "agents": reports,
        "checks": checks,
        "guest_network": "OFF",
        "host_block_device": "NONE",
    }
    dump(output / "native-conformance.json", gate)
    dump(output / "gate.json", {"gate": gate["gate"], "checks": checks})
    print(json.dumps({"gate": gate["gate"], "agents": len(reports), "restored": checks["default_v1_restored"]}, indent=2))
    return 0 if gate["gate"].endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
