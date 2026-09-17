from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
DEFAULT_IMAGE = ROOT / "release/casulo-native-x86_64.img"
DEFAULT_TCAP = ROOT / "release/FloodSurrogate.tcap"
DEFAULT_MANIFEST = ROOT / "release/RELEASE_MANIFEST.json"
DEFAULT_EVIDENCE = ROOT / "evidence/casulo-os-rp01/g7"
KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True, slots=True)
class DemoStep:
    number: int
    name: str
    marker: str
    validate: Callable[[dict[str, str], dict[str, Any]], list[str]]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_serial(serial: str) -> tuple[dict[str, str], dict[str, list[int]], list[str]]:
    values: dict[str, str] = {}
    positions: dict[str, list[int]] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(serial.splitlines(), start=1):
        line = raw_line.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not KEY_PATTERN.fullmatch(key):
            continue
        positions.setdefault(key, []).append(line_number)
        if key in values and values[key] != value:
            errors.append(f"ambiguous duplicate marker {key}")
        elif key in values:
            errors.append(f"duplicate marker {key}")
        else:
            values[key] = value
    return values, positions, errors


def _exact(**expected: str) -> Callable[[dict[str, str], dict[str, Any]], list[str]]:
    def check(values: dict[str, str], _: dict[str, Any]) -> list[str]:
        return [
            f"{key} expected {wanted!r}, got {values.get(key)!r}"
            for key, wanted in expected.items()
            if values.get(key) != wanted
        ]

    return check


def _positive(values: dict[str, str], key: str, minimum: int = 1) -> list[str]:
    raw = values.get(key)
    try:
        parsed = int(raw) if raw is not None else -1
    except ValueError:
        parsed = -1
    return [] if parsed >= minimum else [f"{key} must be an integer >= {minimum}, got {raw!r}"]


def _step_1(values: dict[str, str], _: dict[str, Any]) -> list[str]:
    errors = _exact(G1_BOOT_SMOKE="PASS", ARCH="x86_64")(values, {})
    return errors + _positive(values, "TOPOLOGY_LOGICAL_CPUS", 2)


def _step_2(values: dict[str, str], context: dict[str, Any]) -> list[str]:
    errors = _exact(TCAP_ARTIFACT="FloodSurrogate.tcap", TCAP_VALIDATION="PASS")(values, {})
    expected_hash = context.get("tcap_sha256")
    actual_hash = values.get("TCAP_HASH_SHA256")
    if expected_hash is None:
        errors.append("host TCAP hash is unavailable")
    elif actual_hash != expected_hash:
        errors.append(f"TCAP_HASH_SHA256 does not match the host artifact ({actual_hash!r})")
    return errors


def _step_3(values: dict[str, str], _: dict[str, Any]) -> list[str]:
    errors = _exact(
        FLOOD_SURROGATE_EXECUTION="PASS",
        FLOOD_SURROGATE_EXIT_STATUS="0",
        PROCESS_SEPARATE_CR3="PASS",
    )(values, {})
    return errors + _positive(values, "RING3_PROCESSES")


def _step_7(values: dict[str, str], _: dict[str, Any]) -> list[str]:
    errors = _exact(SCHEDULER_TIMELINE="PASS")(values, {})
    errors += _positive(values, "FLOW_DISPATCHES")
    errors += _positive(values, "ATTRACTOR_AUDIT_DISPATCHES")
    return errors


def _step_10(values: dict[str, str], _: dict[str, Any]) -> list[str]:
    errors = _exact(
        CASULO_SHELL_SCOPE="bounded-read-only-parser/0.1",
        CASULO_SHELL_SELF_TEST="PASS",
        G7_DEMO_COMPLETE="PASS",
        SHUTDOWN_PATH="isa-debug-exit/0.1",
        REBOOT_PATH="8042-reset-probe-validated/0.1",
    )(values, {})
    if values.get("ENERGY_STATUS") not in {"measured", "unavailable"}:
        errors.append("ENERGY_STATUS must be measured or unavailable")
    if values.get("TIMING_STATUS") not in {"measured", "unavailable"}:
        errors.append("TIMING_STATUS must be measured or unavailable")
    return errors


DEMO_STEPS = (
    DemoStep(1, "boot identity and topology", "G1_BOOT_SMOKE", _step_1),
    DemoStep(2, "TCAP integrity and provenance", "TCAP_VALIDATION", _step_2),
    DemoStep(3, "isolated FloodSurrogate execution", "FLOOD_SURROGATE_EXECUTION", _step_3),
    DemoStep(4, "conventional deterministic policy", "CONVENTIONAL_POLICY", _exact(CONVENTIONAL_POLICY="PASS")),
    DemoStep(5, "semantic deterministic policy", "SEMANTIC_POLICY", _exact(SEMANTIC_POLICY="PASS")),
    DemoStep(6, "equivalence judge", "EQUIVALENCE_JUDGE", _exact(EQUIVALENCE_JUDGE="PASS")),
    DemoStep(7, "FLOW and ATTRACTOR timeline", "SCHEDULER_TIMELINE", _step_7),
    DemoStep(8, "audit non-starvation", "NON_STARVATION", _exact(NON_STARVATION="PASS", AUDIT_STARVATION="0")),
    DemoStep(
        9,
        "corrupted TCAP quarantine without execution",
        "TCAP_CORRUPT_RESULT",
        _exact(TCAP_CORRUPT_RESULT="QUARANTINE", TCAP_CORRUPT_EXECUTED="0"),
    ),
    DemoStep(10, "honest measurements and supported exit", "G7_DEMO_COMPLETE", _step_10),
)


def validate_serial(serial: str, *, tcap_sha256: str | None, returncode: int) -> dict[str, Any]:
    values, positions, parsing_errors = parse_serial(serial)
    context = {"tcap_sha256": tcap_sha256}
    steps: list[dict[str, Any]] = []
    previous_position = 0
    ordering_errors: list[str] = []
    for step in DEMO_STEPS:
        errors = step.validate(values, context)
        marker_positions = positions.get(step.marker, [])
        if len(marker_positions) == 1:
            position = marker_positions[0]
            if position <= previous_position:
                ordering_errors.append(f"step {step.number} marker is out of order")
            previous_position = max(previous_position, position)
        else:
            position = None
        steps.append(
            {
                "number": step.number,
                "name": step.name,
                "marker": step.marker,
                "line": position,
                "status": "PASS" if not errors else "BLOCKED",
                "errors": errors,
            }
        )
    if returncode != 33:
        ordering_errors.append(f"QEMU supported exit expected return code 33, got {returncode}")
    if "EQUIVALENCE_JUDGE" in positions:
        judge_line = positions["EQUIVALENCE_JUDGE"][0]
        premature = [key for key in ("TIMING_STATUS", "ENERGY_STATUS") if positions.get(key, [10**9])[0] < judge_line]
        if premature:
            ordering_errors.append("measurements appeared before equivalence: " + ", ".join(premature))
    passed = not parsing_errors and not ordering_errors and all(step["status"] == "PASS" for step in steps)
    return {
        "status": "PASS" if passed else "BLOCKED",
        "pass": passed,
        "steps": steps,
        "parsing_errors": parsing_errors,
        "ordering_errors": ordering_errors,
        "observed_marker_count": len(values),
    }


def verify_tcap(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    result: dict[str, Any] = {
        "path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
        "status": "BLOCKED",
        "sha256": None,
        "valid_original": False,
        "corruption_rejected": False,
        "error": None,
    }
    if not path.is_file() or path.is_symlink():
        result["error"] = "TCAP is absent or is not a regular file"
        return result
    try:
        from casulo.t.tcap import TcapError, parse_tcap

        raw = path.read_bytes()
        package = parse_tcap(raw)
        result["sha256"] = hashlib.sha256(raw).hexdigest()
        result["content_sha256"] = package.manifest["content_sha256"]
        result["valid_original"] = True
        corrupted = bytearray(raw)
        corrupted[-1] ^= 0x01
        try:
            parse_tcap(bytes(corrupted))
        except TcapError as exc:
            result["corruption_rejected"] = True
            result["corruption_error"] = str(exc)
        else:
            result["error"] = "controlled corruption was accepted"
        if result["valid_original"] and result["corruption_rejected"]:
            result["status"] = "PASS"
    except Exception as exc:  # evidence must record malformed/unloadable artifacts
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def verify_release_manifest(path: Path, image: Path, tcap: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    image = image.expanduser().resolve()
    tcap = tcap.expanduser().resolve()
    result: dict[str, Any] = {"path": str(path), "status": "BLOCKED", "errors": []}
    if not path.is_file() or path.is_symlink():
        result["errors"].append("release manifest is absent or not a regular file")
        return result
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["errors"].append(f"invalid release manifest: {exc}")
        return result
    if manifest.get("schema") not in {
        "casulo-so-release-manifest/0.1",
        "casulo-so-release-manifest/0.2",
    }:
        result["errors"].append("unexpected release manifest schema")
    if manifest.get("physical_device_written") is not False:
        result["errors"].append("physical_device_written must be false for this harness")
    if manifest.get("publication_performed") is not False:
        result["errors"].append("publication_performed must be false for this local rehearsal")
    artifacts = manifest.get("artifacts")
    artifact_map = {
        item.get("path"): item
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    } if isinstance(artifacts, list) else {}
    for artifact in (image, tcap):
        relative = artifact.relative_to(ROOT).as_posix() if artifact.is_relative_to(ROOT) else str(artifact)
        entry = artifact_map.get(relative)
        if not artifact.is_file() or artifact.is_symlink():
            result["errors"].append(f"missing regular artifact: {relative}")
        elif not isinstance(entry, dict):
            result["errors"].append(f"manifest does not list {relative}")
        elif entry.get("sha256") != sha256(artifact) or entry.get("bytes") != artifact.stat().st_size:
            result["errors"].append(f"manifest digest or size mismatch: {relative}")
    result["status"] = "PASS" if not result["errors"] else "BLOCKED"
    result["sha256"] = sha256(path)
    return result


def run_rehearsal(
    *,
    image: Path,
    tcap: Path,
    manifest: Path,
    repeat: int,
    timeout: float,
    serial_fixture: str | None = None,
) -> dict[str, Any]:
    tcap_check = verify_tcap(tcap)
    manifest_check = verify_release_manifest(manifest, image, tcap)
    records: list[dict[str, Any]] = []
    evidence_kind = "synthetic_parser_test" if serial_fixture is not None else "real_qemu_rehearsal"
    if serial_fixture is not None:
        for _ in range(repeat):
            records.append(
                {
                    "returncode": 33,
                    "serial": serial_fixture,
                    "validation": validate_serial(
                        serial_fixture,
                        tcap_sha256=tcap_check.get("sha256"),
                        returncode=33,
                    ),
                }
            )
    else:
        run_qemu_path = ROOT / "os/tools/run_qemu.py"
        spec = importlib.util.spec_from_file_location("casulo_demo_run_qemu", run_qemu_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load the QEMU runner")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        safe_image = module.safe_regular_workspace_file(image)
        for dependency in (module.DEFAULT_QEMU, module.DEFAULT_CODE, module.DEFAULT_VARS):
            if not dependency.is_file():
                raise RuntimeError(f"missing QEMU dependency: {dependency}")
        for _ in range(repeat):
            boot = module.boot_once(
                safe_image,
                module.DEFAULT_QEMU,
                module.DEFAULT_CODE,
                module.DEFAULT_VARS,
                timeout,
            )
            serial = str(boot["serial"])
            records.append(
                {
                    "returncode": boot["returncode"],
                    "serial": serial,
                    "validation": validate_serial(
                        serial,
                        tcap_sha256=tcap_check.get("sha256"),
                        returncode=int(boot["returncode"]),
                    ),
                }
            )
    all_serial_pass = bool(records) and all(item["validation"]["pass"] for item in records)
    preflight_pass = tcap_check["status"] == "PASS" and manifest_check["status"] == "PASS"
    real_evidence = evidence_kind == "real_qemu_rehearsal"
    g7_pass = real_evidence and preflight_pass and all_serial_pass and repeat == 10
    return {
        "schema": "casulo-g7-demo-rehearsal/0.1",
        "evidence_kind": evidence_kind,
        "required_rehearsals": 10,
        "attempts": len(records),
        "serial_passed": sum(bool(item["validation"]["pass"]) for item in records),
        "all_serial_pass": all_serial_pass,
        "preflight_pass": preflight_pass,
        "g7_pass": g7_pass,
        "status": "PASS" if g7_pass else "BLOCKED",
        "host_block_devices_attached": False,
        "image_attached_read_only": real_evidence,
        "synthetic_evidence_can_satisfy_g7": False,
        "tcap": tcap_check,
        "release_manifest": manifest_check,
        "results": records,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Casulo SO G7 automated demo evidence",
        "",
        f"- Status: **{summary['status']}**",
        f"- Evidence kind: `{summary['evidence_kind']}`",
        f"- Rehearsals: {summary['attempts']}/10",
        f"- Serial validations passed: {summary['serial_passed']}/{summary['attempts']}",
        f"- TCAP host validation: {summary['tcap']['status']}",
        f"- Release manifest validation: {summary['release_manifest']['status']}",
        "- Physical device written: no",
        "",
    ]
    if summary["results"]:
        first = summary["results"][0]["validation"]
        lines += ["## Ten-step contract (first rehearsal)", "", "| # | Step | Status | Evidence gap |", "|---:|---|---|---|"]
        for step in first["steps"]:
            gap = "; ".join(step["errors"]) or "none"
            lines.append(f"| {step['number']} | {step['name']} | {step['status']} | {gap} |")
        for error in first["parsing_errors"] + first["ordering_errors"]:
            lines.append(f"\n- Protocol error: {error}")
    lines += [
        "",
        "Synthetic serial fixtures validate only the parser and can never satisfy G7.",
        "A blocked result is expected until the kernel emits the complete G3/G4 demo protocol.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Casulo SO G7 ten-step demo rehearsal.")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--tcap", type=Path, default=DEFAULT_TCAP)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--serial-fixture", type=Path, help="parser diagnostics only; never valid G7 evidence")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        raise SystemExit("repeat must be between 1 and 10")
    fixture = args.serial_fixture.read_text(encoding="utf-8") if args.serial_fixture else None
    summary = run_rehearsal(
        image=args.image,
        tcap=args.tcap,
        manifest=args.manifest,
        repeat=args.repeat,
        timeout=args.timeout,
        serial_fixture=fixture,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"demo-rehearsal-{args.repeat}"
    (args.output_dir / f"{stem}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / f"{stem}.md").write_text(render_markdown(summary), encoding="utf-8")
    printable = {key: value for key, value in summary.items() if key != "results"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0 if summary["g7_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
