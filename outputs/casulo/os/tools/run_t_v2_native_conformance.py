from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from casulo.t.v2_runtime import V2ReferenceRuntime, V2RuntimeError  # noqa: E402
from casulo.t.v2_tcap import (  # noqa: E402
    TcapV2Builder,
    build_native_probe_bundle,
    verify_tcap_v2,
)
from run_qemu import DEFAULT_CODE, DEFAULT_QEMU, DEFAULT_VARS, boot_once, sha256  # noqa: E402


CASES = (
    ("publish", {"confirmed": True, "hard_statuses": ["PASS", "PASS"], "cancelled": False}, ("manifest",)),
    ("unconfirmed", {"confirmed": False, "hard_statuses": ["PASS"], "cancelled": False}, ("manifest",)),
    ("unknown-hard", {"confirmed": True, "hard_statuses": ["UNKNOWN"], "cancelled": False}, ("manifest",)),
    ("cancelled", {"confirmed": True, "hard_statuses": ["PASS"], "cancelled": True}, ("manifest",)),
    ("denied", {"confirmed": True, "hard_statuses": ["PASS"], "cancelled": False}, ()),
)


def extract_marker(serial: str, marker: str) -> str:
    prefix = marker + "="
    values = [line[len(prefix):] for line in serial.splitlines() if line.startswith(prefix)]
    if len(values) != 1:
        raise ValueError(f"expected exactly one {marker}, observed {len(values)}")
    return values[0]


def logical_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    ignored = {"runtime_id", "monotonic_timestamp_ns", "receipt_hash"}
    return {key: value for key, value in receipt.items() if key not in ignored}


def main() -> int:
    parser = argparse.ArgumentParser(description="T/2.0 reference, productive and Casulo Native differential gate")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents or output.exists():
        raise SystemExit("output must be a new directory inside the repository")
    output.mkdir(parents=True)

    tcap = TcapV2Builder().build(
        (ROOT / "examples/t-v2/owner_publish.t",),
        output / "owner-publish.tcap",
        entry_module="owner.publish",
        entry_function="decide",
        tests={"properties": ["hard_unknown_never_publishes", "capability_required"]},
    )
    _, manifest, typed = verify_tcap_v2(tcap.directory)
    ir = typed["modules"][0]
    runtime = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
    if not runtime.is_file():
        raise SystemExit("productive runtime missing; build t-runtime offline first")
    dependencies = (Path(DEFAULT_QEMU), Path(DEFAULT_CODE), Path(DEFAULT_VARS))
    if any(not item.is_file() for item in dependencies):
        raise SystemExit(f"QEMU/OVMF dependency missing: {dependencies}")

    case_reports: list[dict[str, Any]] = []
    for index, (case_id, payload, grants) in enumerate(CASES, 1):
        case_dir = output / f"case-{index:02d}-{case_id}"
        case_dir.mkdir()
        input_path = case_dir / "input.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        surface = "publish_commit"
        scope = f"native-conformance:{case_id}"
        reference = V2ReferenceRuntime().execute(
            ir, "decide", payload, grants=frozenset(grants),
            source_hash=manifest["sources"][0]["sha256"], tcap_hash=tcap.tcap_hash,
            scope_id=scope, surface_id=surface,
        )
        productive_run = subprocess.run(
            [str(runtime), str(tcap.directory), "decide", str(input_path), ",".join(grants), surface, scope, "0" * 64],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
        )
        if productive_run.returncode != 0:
            raise SystemExit(f"productive runtime failed for {case_id}: {productive_run.stderr}")
        productive = json.loads(productive_run.stdout)
        bundle = build_native_probe_bundle(
            tcap.directory, case_dir / "native-probe.json", function_name="decide", payload=payload,
            grants=grants, surface_id=surface, scope_id=scope,
        )
        environment = os.environ.copy()
        environment["CASULO_TCAP_RAMDISK"] = str(bundle)
        build = subprocess.run(
            ["cargo", "+nightly-2026-02-01", "-Z", "bindeps", "build", "--manifest-path", "os/Cargo.toml", "--release", "--locked", "--offline"],
            cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False,
        )
        if build.returncode != 0:
            raise SystemExit(f"Native build failed for {case_id}: {build.stdout}\n{build.stderr}")
        launcher = ROOT / "os/target/release" / ("casulo-os-image.exe" if os.name == "nt" else "casulo-os-image")
        launched = subprocess.run([str(launcher)], capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
        image = Path(launched.stdout.strip()).resolve()
        boot = boot_once(image, *dependencies, args.timeout)
        serial = str(boot["serial"])
        native_observable = json.loads(extract_marker(serial, "TCAP_V2_OBSERVABLE"))
        native_receipt = json.loads(extract_marker(serial, "TCAP_V2_RECEIPT"))
        reference_receipt = reference.receipt.to_dict()
        productive_receipt = productive["runtime_receipt"]
        checks = {
            "qemu_success": boot["returncode"] == 33 and boot["timed_out"] is False,
            "native_gate": "TCAP_V2_GATE=PASS" in serial,
            "guest_isolated": "TCAP_V2_ISOLATION=qemu-guest-no-network-no-host-block-device" in serial,
            "corruption_quarantined": "TCAP_V2_CORRUPTION=QUARANTINE" in serial,
            "observable_reference_productive": reference.observable() == productive["observable"],
            "observable_reference_native": reference.observable() == native_observable,
            "receipt_reference_productive": logical_receipt(reference_receipt) == logical_receipt(productive_receipt),
            "receipt_reference_native": logical_receipt(reference_receipt) == logical_receipt(native_receipt),
            "runtime_ids_distinct": {reference_receipt["runtime_id"], productive_receipt["runtime_id"], native_receipt["runtime_id"]} == {"t-runtime/reference-2.0", "t-runtime/rust-2.0", "t-runtime/native-2.0"},
        }
        (case_dir / "serial.log").write_text(serial, encoding="utf-8")
        case_reports.append({
            "case_id": case_id, "payload": payload, "grants": list(grants), "checks": checks,
            "observable": native_observable, "reference_receipt": reference_receipt,
            "productive_receipt": productive_receipt, "native_receipt": native_receipt,
            "bundle_sha256": sha256(bundle), "image_sha256": sha256(image),
            "serial_sha256": hashlib.sha256(serial.encode("utf-8")).hexdigest(),
        })
    # A second TCAP deliberately has too few logical steps. All three runtimes
    # must fail with the same state; Native must not emit an observable/receipt.
    exhaustion_source = output / "resource-exhaustion.t"
    exhaustion_source.write_text(
        """language T/2.0
module test.exhaust
budget steps 1
budget deadline_ms 5000
schema version 1

record Input
  member cancelled: Bool

fn decide(input: Input) -> Result<Text,Text>
  cancel if input.cancelled
  return ok \"PASS\"
""",
        encoding="utf-8", newline="\n",
    )
    exhausted = TcapV2Builder().build(
        (exhaustion_source,), output / "resource-exhaustion.tcap",
        entry_module="test.exhaust", entry_function="decide",
    )
    _, exhausted_manifest, exhausted_typed = verify_tcap_v2(exhausted.directory)
    try:
        V2ReferenceRuntime().execute(exhausted_typed["modules"][0], "decide", {"cancelled": False})
        reference_error = None
    except V2RuntimeError as error:
        reference_error = str(error)
    exhausted_input = output / "resource-exhaustion-input.json"
    exhausted_input.write_text('{"cancelled":false}\n', encoding="utf-8", newline="\n")
    productive_exhausted = subprocess.run(
        [str(runtime), str(exhausted.directory), "decide", str(exhausted_input), ""],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
    )
    exhausted_bundle = build_native_probe_bundle(
        exhausted.directory, output / "resource-exhaustion-native-probe.json",
        function_name="decide", payload={"cancelled": False}, grants=(),
        surface_id="agent_behavior", scope_id="native-conformance:resource-exhaustion",
    )
    exhausted_environment = os.environ.copy()
    exhausted_environment["CASULO_TCAP_RAMDISK"] = str(exhausted_bundle)
    exhausted_build = subprocess.run(
        ["cargo", "+nightly-2026-02-01", "-Z", "bindeps", "build", "--manifest-path", "os/Cargo.toml", "--release", "--locked", "--offline"],
        cwd=ROOT, env=exhausted_environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False,
    )
    if exhausted_build.returncode != 0:
        raise SystemExit(f"Native exhaustion build failed: {exhausted_build.stdout}\n{exhausted_build.stderr}")
    exhausted_launcher = ROOT / "os/target/release" / ("casulo-os-image.exe" if os.name == "nt" else "casulo-os-image")
    exhausted_image = Path(subprocess.run([str(exhausted_launcher)], capture_output=True, text=True, encoding="utf-8", timeout=10, check=True).stdout.strip()).resolve()
    exhausted_boot = boot_once(exhausted_image, *dependencies, args.timeout)
    exhausted_serial = str(exhausted_boot["serial"])
    exhaustion_checks = {
        "reference_exhausted": reference_error == "RESOURCE_STEPS_EXHAUSTED",
        "productive_exhausted": productive_exhausted.returncode == 2 and "RESOURCE_STEPS_EXHAUSTED" in productive_exhausted.stderr,
        "native_exhausted": exhausted_boot["returncode"] == 35 and "TCAP_V2_REJECT_REASON=RESOURCE_STEPS_EXHAUSTED" in exhausted_serial,
        "native_no_observable": "TCAP_V2_OBSERVABLE=" not in exhausted_serial and "TCAP_V2_EXECUTION_COUNT=0" in exhausted_serial,
    }
    (output / "resource-exhaustion-serial.log").write_text(exhausted_serial, encoding="utf-8")
    negative_cases = [{
        "case_id": "resource-exhaustion", "checks": exhaustion_checks,
        "reference_error": reference_error, "productive_stderr": productive_exhausted.stderr.strip(),
        "native_reject_reason": "RESOURCE_STEPS_EXHAUSTED" if exhaustion_checks["native_exhausted"] else None,
        "tcap_hash": exhausted_manifest["tcap_hash"], "bundle_sha256": sha256(exhausted_bundle),
        "image_sha256": sha256(exhausted_image),
    }]
    passed = all(all(case["checks"].values()) for case in case_reports) and all(all(case["checks"].values()) for case in negative_cases)
    report = {
        "schema": "casulo.t-v2-native-conformance/1.0",
        "status": "PASS" if passed else "FAIL",
        "scope": "correctness-only differential execution; not performance or scientific benchmark",
        "tcap_hash": tcap.tcap_hash,
        "cases": case_reports,
        "negative_cases": negative_cases,
        "native_isolation": "QEMU guest, network disabled, immutable image, no host block device",
        "native_ring3": False,
        "limitations": ["T/2.0 interpreter executes in the Native kernel for this gate; process-level ring-3 confinement remains a later hardening item."],
        "scientific_benchmark": "NOT_STARTED",
    }
    (output / "native-conformance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "tcap_hash": tcap.tcap_hash, "cases": len(case_reports), "negative_cases": len(negative_cases)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
