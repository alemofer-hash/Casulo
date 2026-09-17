from __future__ import annotations

import argparse
from dataclasses import replace
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .energy_v1.analysis import analyze_campaign
from .energy_v1.artifacts import render_report, seal_campaign, verify_campaign
from .energy_v1.capabilities import preflight_energy
from .energy_v1.paired_runner import (
    CallbackWallSource,
    RaplPackageSource,
    calibrate_k,
    equivalence_gate,
    load_commands,
    run_paired_campaign,
)
from .energy_v1.protocol import EnergyProtocol, deterministic_schedule, freeze_protocol, load_protocol
from .energy_v1.schemas import iter_jsonl, read_json, write_json
from .energy_v1.wall_meter import fetch_local_api
from .energy_v1.hwinfo import inspect_file, watch_file
from .energy_v1.hwinfo_campaign import (
    DEFAULT_CAMPAIGN_ID as HWINFO_DEFAULT_CAMPAIGN_ID,
    analyze_hwinfo_campaign,
    calibrate_campaign as calibrate_hwinfo_campaign,
    execute_pairs as execute_hwinfo_pairs,
    finalize_source_and_seal as finalize_hwinfo_source_and_seal,
    initialize_campaign as initialize_hwinfo_campaign,
    inspect_hwinfo,
    prepare_workers as prepare_hwinfo_workers,
    render_hwinfo_report,
    run_equivalence as run_hwinfo_equivalence,
)
from .energy_v1.hwinfo_recovery import (
    RECOVERY_CAMPAIGN_ID,
    ThermalRecoveryBlocked,
    analyze_recovery_campaign,
    finalize_active_cooling_block,
    finalize_recovery_evidence,
    finalize_polling_block,
    initialize_recovery_campaign,
    render_recovery_report,
    run_definitive_recovery_campaign,
    run_thermal_recovery_calibration,
    validate_recovery_polling,
)


ROOT = Path(__file__).resolve().parents[3]
ENERGY_ROOT = ROOT / "energy"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casulo-energy",
        description="Casulo LiveLab Energy V1; physical joules only, fail closed.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    hwinfo = sub.add_parser("hwinfo")
    hwinfo_sub = hwinfo.add_subparsers(dest="hwinfo_command", required=True)
    for name in ("inspect", "watch", "calibrate", "recover"):
        item = hwinfo_sub.add_parser(name)
        item.add_argument("--csv", type=Path, required=True)
        item.add_argument("--campaign-id", default=HWINFO_DEFAULT_CAMPAIGN_ID)
        item.add_argument("--campaign-dir", type=Path)
        item.add_argument("--tcap", type=Path, default=ROOT / "release" / "FloodSurrogate.tcap")
        if name == "watch":
            item.add_argument("--timeout-seconds", type=float, default=60.0)
        if name == "recover":
            item.add_argument("--polling-ms", type=int, choices=(250, 500), default=500)
            item.add_argument(
                "--thermal-abort-c",
                type=float,
                choices=(74.5, 80.0, 90.0),
                default=74.5,
            )
            item.add_argument(
                "--start-threshold-c",
                type=float,
                choices=(60.0, 70.0),
                default=None,
            )
            item.add_argument(
                "--phase",
                choices=("preflight", "calibrate", "run", "analyze", "report"),
                default="preflight",
            )
    for name in ("preflight", "calibrate", "smoke", "run", "analyze", "report"):
        item = sub.add_parser(name)
        item.add_argument("--campaign-id", default=None)
        item.add_argument("--campaign-dir", type=Path)
        if name == "preflight":
            item.add_argument("--domain", choices=("CPU_PACKAGE_RAPL", "TOTAL_SYSTEM_WALL"), default="CPU_PACKAGE_RAPL")
            item.add_argument("--candidate", default="t-general-ir-tcap/0.1")
            item.add_argument("--baseline", default="pytorch-eager-fullstep/1")
            item.add_argument("--workload", default="flood-surrogate-canary-400")
            item.add_argument("--wall-meter-file", type=Path)
            item.add_argument("--wall-meter-api")
        if name in {"calibrate", "smoke", "run"}:
            item.add_argument("--commands", type=Path)
        if name == "run":
            item.add_argument("--source", choices=("hwinfo-csv",))
            item.add_argument("--csv", type=Path)
            item.add_argument("--comparison", choices=("flood-tcap-vs-eager",))
            item.add_argument("--tcap", type=Path, default=ROOT / "release" / "FloodSurrogate.tcap")
        if name == "calibrate":
            item.add_argument("--target-seconds", type=float)
        if name in {"smoke", "run"}:
            item.add_argument("--absolute-tolerance", type=float, default=1e-9)
            item.add_argument("--relative-tolerance", type=float, default=1e-9)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "hwinfo":
        try:
            return _hwinfo(args)
        except Exception as exc:
            print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
    campaign_id = args.campaign_id or _default_campaign_id()
    directory = (args.campaign_dir or ENERGY_ROOT / campaign_id).resolve()
    try:
        if args.command == "preflight":
            return _preflight(args, campaign_id, directory)
        if args.command == "calibrate":
            return _calibrate(args, directory)
        if args.command == "smoke":
            return _smoke(args, directory)
        if args.command == "run" and args.source == "hwinfo-csv":
            return _run_hwinfo(args, campaign_id, directory)
        if args.command == "run":
            return _run(args, directory)
        if args.command == "analyze":
            if _is_hwinfo_campaign(directory):
                value = analyze_hwinfo_campaign(directory)
                print(json.dumps(value, ensure_ascii=False, indent=2))
                return 0
            return _analyze(directory)
        if args.command == "report":
            if _is_hwinfo_campaign(directory):
                path = render_hwinfo_report(directory)
                print(json.dumps({"status": "PASS", "report": str(path)}, ensure_ascii=False, indent=2))
                return 0
            return _report(directory)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 1


def _hwinfo(args: argparse.Namespace) -> int:
    if args.hwinfo_command == "inspect":
        value = inspect_hwinfo(args.csv)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value["status"] == "PASS" else 2
    if args.hwinfo_command == "watch":
        _, parsed, _ = inspect_file(args.csv)
        value = watch_file(
            args.csv,
            after_timestamp_utc=parsed.last_timestamp_utc,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value["status"] == "PASS" else 2
    if args.hwinfo_command == "calibrate":
        directory = (args.campaign_dir or ENERGY_ROOT / args.campaign_id).resolve()
        directory = initialize_hwinfo_campaign(ENERGY_ROOT, args.csv, args.tcap, args.campaign_id) if args.campaign_dir is None else initialize_hwinfo_campaign(directory.parent, args.csv, args.tcap, directory.name)
        native, eager, _ = prepare_hwinfo_workers(directory, args.tcap)
        try:
            if not (directory / "equivalence" / "gate.json").exists():
                run_hwinfo_equivalence(directory, (native, eager), args.csv, args.tcap)
            value = calibrate_hwinfo_campaign(directory, (native, eager), args.csv, args.tcap)
        finally:
            native.stop()
            eager.stop()
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value["status"] == "PASS" else 3
    if args.hwinfo_command == "recover":
        requested = args.campaign_id
        if requested == HWINFO_DEFAULT_CAMPAIGN_ID:
            requested = RECOVERY_CAMPAIGN_ID
        if args.phase == "preflight":
            directory = initialize_recovery_campaign(
                ENERGY_ROOT,
                args.csv,
                args.tcap,
                requested,
                polling_mode_ms=args.polling_ms,
                thermal_abort_c=args.thermal_abort_c,
                start_threshold_override_c=args.start_threshold_c,
            )
            value = validate_recovery_polling(directory, args.csv)
            if value["status"] == "BLOCKED_HWINFO_POLLING_NOT_CHANGED":
                seals = finalize_polling_block(directory, args.csv, value)
                output = {"status": value["status"], "campaign": str(directory), "polling": value, "seals": seals}
                print(json.dumps(output, ensure_ascii=False, indent=2))
                return 2
            output = {"status": "POLLING_READY", "campaign": str(directory), "polling": value, "next_stage": "observer_and_thermal_recovery"}
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0
        directory = (args.campaign_dir or ENERGY_ROOT / requested).resolve()
        if args.phase == "calibrate":
            try:
                value = run_thermal_recovery_calibration(directory, args.csv, args.tcap)
            except ThermalRecoveryBlocked as exc:
                if args.polling_ms == 250 and exc.state == "BLOCKED_ACTIVE_COOLING_REQUIRED":
                    seals = finalize_active_cooling_block(directory, args.csv)
                    print(
                        json.dumps(
                            {
                                "status": exc.state,
                                "campaign": str(directory),
                                "detail": exc.detail,
                                "seals": seals,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    return 2
                raise
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0
        if args.phase == "run":
            value = run_definitive_recovery_campaign(directory, args.csv, args.tcap)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0 if value["status"] == "COLLECTION_COMPLETE" else 4
        if args.phase == "analyze":
            value = analyze_recovery_campaign(directory)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0 if value["valid_pairs"] == 21 else 4
        analysis = read_json(directory / "analysis.json")
        report = render_recovery_report(directory, analysis)
        seals = finalize_recovery_evidence(directory, args.csv)
        print(json.dumps({"status": analysis["terminal_state"], "campaign": str(directory), "report": str(report), "seals": seals}, ensure_ascii=False, indent=2))
        return 0 if analysis["valid_pairs"] == 21 else 4
    raise ValueError("unknown HWiNFO command")


def _run_hwinfo(args: argparse.Namespace, campaign_id: str, directory: Path) -> int:
    if args.csv is None or args.comparison != "flood-tcap-vs-eager":
        raise ValueError("HWiNFO run requires --csv and --comparison flood-tcap-vs-eager")
    directory = initialize_hwinfo_campaign(directory.parent, args.csv, args.tcap, directory.name)
    native, eager, _ = prepare_hwinfo_workers(directory, args.tcap)
    try:
        if not (directory / "equivalence" / "gate.json").exists():
            run_hwinfo_equivalence(directory, (native, eager), args.csv, args.tcap)
        if not (directory / "calibration.json").exists():
            calibrate_hwinfo_campaign(directory, (native, eager), args.csv, args.tcap)
        execute_hwinfo_pairs(directory, (native, eager), args.csv, args.tcap)
    finally:
        native.stop()
        eager.stop()
    analysis = analyze_hwinfo_campaign(directory)
    report = render_hwinfo_report(directory, analysis)
    seals = finalize_hwinfo_source_and_seal(directory, args.csv)
    value = {"status": analysis["terminal_state"], "campaign": str(directory), "report": str(report), "seals": seals}
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if analysis["complete_design"] else 4


def _is_hwinfo_campaign(directory: Path) -> bool:
    protocol = directory / "protocol.json"
    if not protocol.exists():
        return False
    try:
        return read_json(protocol).get("schema") == "casulo-hwinfo-energy-campaign/1.0"
    except Exception:
        return False


def _preflight(args: argparse.Namespace, campaign_id: str, directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw").mkdir(exist_ok=True)
    (directory / "rejected").mkdir(exist_ok=True)
    protocol_path = directory / "protocol.json"
    if not protocol_path.exists():
        logical = max(1, min(4, __import__("os").cpu_count() or 1))
        protocol = EnergyProtocol(
            campaign_id=campaign_id,
            candidate=args.candidate,
            baseline=args.baseline,
            workload=args.workload,
            energy_domain=args.domain,
            threads=logical,
            affinity=tuple(range(logical)),
        )
        freeze_protocol(directory, protocol)
    else:
        protocol = load_protocol(protocol_path)
        if protocol.campaign_id != campaign_id:
            raise ValueError("campaign ID differs from frozen protocol")
    capabilities = preflight_energy(
        wall_meter_path=args.wall_meter_file,
        wall_meter_url=args.wall_meter_api,
        thermal_limit_c=protocol.maximum_temperature_c,
    )
    environment = capabilities.pop("environment")
    write_json(directory / "environment.json", environment)
    write_json(directory / "capabilities.json", capabilities)
    state = {
        "status": "READY" if protocol.energy_domain in capabilities["physical_domains"] else "BLOCKED_PHYSICAL_INSTRUMENT",
        "campaign_id": protocol.campaign_id,
        "domain": protocol.energy_domain,
        "workload_started": False,
        "reason_codes": capabilities["reason_codes"],
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(directory / "preflight.json", state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0 if state["status"] == "READY" else 2


def _calibrate(args: argparse.Namespace, directory: Path) -> int:
    protocol = load_protocol(directory / "protocol.json")
    capabilities = read_json(directory / "capabilities.json")
    if protocol.energy_domain not in capabilities.get("physical_domains", []):
        value = _blocked_stage("calibrate", capabilities.get("reason_codes", []))
        write_json(directory / "calibration.json", value)
        print(json.dumps(value, indent=2))
        return 2
    if args.commands is None:
        raise ValueError("--commands is required after a physical source passes preflight")
    commands = load_commands(args.commands)
    target = args.target_seconds or (
        protocol.preferred_rapl_window_seconds if protocol.energy_domain == "CPU_PACKAGE_RAPL"
        else protocol.minimum_wall_window_seconds
    )
    results = {
        name: calibrate_k(commands[name], target_seconds=target)
        for name in (protocol.baseline, protocol.candidate)
    }
    value = {"status": "PASS", "target_seconds": target, "implementations": results}
    write_json(directory / "calibration.json", value)
    calibrated = {name: result["K"] for name, result in results.items()}
    write_json(directory / "calibrated-k.json", calibrated)
    if (directory / "raw" / "samples.jsonl").exists():
        raise ValueError("cannot freeze K after scientific samples exist")
    # Calibration is not a definitive sample. Preserve the pre-calibration
    # protocol, then freeze K and regenerate the still-unobserved schedule.
    write_json(directory / "protocol-precalibration.json", protocol.to_dict())
    protocol = replace(protocol, K=calibrated)
    write_json(directory / "protocol.json", protocol.to_dict())
    write_json(directory / "schedule.json", deterministic_schedule(protocol))
    print(json.dumps(value, indent=2))
    return 0


def _smoke(args: argparse.Namespace, directory: Path) -> int:
    protocol = load_protocol(directory / "protocol.json")
    capabilities = read_json(directory / "capabilities.json")
    if protocol.energy_domain not in capabilities.get("physical_domains", []):
        value = _blocked_stage("smoke", capabilities.get("reason_codes", []))
        write_json(directory / "smoke.json", value)
        print(json.dumps(value, indent=2))
        return 2
    if args.commands is None:
        raise ValueError("--commands is required after a physical source passes preflight")
    commands = load_commands(args.commands)
    equivalence = equivalence_gate(
        commands, protocol.candidate, protocol.baseline,
        absolute_tolerance=args.absolute_tolerance,
        relative_tolerance=args.relative_tolerance,
    )
    value = {"status": "PASS" if equivalence["status"] == "PASS" else "FAIL", "equivalence": equivalence, "energy_window_executed": False}
    write_json(directory / "smoke.json", value)
    print(json.dumps(value, indent=2))
    return 0 if value["status"] == "PASS" else 3


def _run(args: argparse.Namespace, directory: Path) -> int:
    protocol = load_protocol(directory / "protocol.json")
    capabilities = read_json(directory / "capabilities.json")
    if protocol.energy_domain not in capabilities.get("physical_domains", []):
        value = _blocked_stage("run", capabilities.get("reason_codes", []))
        write_json(directory / "run.json", value)
        print(json.dumps(value, indent=2))
        return 2
    if args.commands is None:
        raise ValueError("--commands is required after a physical source passes preflight")
    if not protocol.K:
        raise ValueError("definitive protocol has no frozen K; create it from calibrated-k.json before running")
    commands = load_commands(args.commands)
    equivalence = equivalence_gate(commands, protocol.candidate, protocol.baseline, absolute_tolerance=args.absolute_tolerance, relative_tolerance=args.relative_tolerance)
    if equivalence["status"] != "PASS":
        write_json(directory / "equivalence.json", equivalence)
        return 3
    source = _rapl_source(capabilities) if protocol.energy_domain == "CPU_PACKAGE_RAPL" else _wall_source(capabilities)
    if source is None:
        value = _blocked_stage("run", ["validated_live_energy_source_not_constructible"])
        write_json(directory / "run.json", value)
        return 2
    result = run_paired_campaign(directory, protocol, commands, source, equivalence)
    write_json(directory / "equivalence.json", equivalence)
    write_json(directory / "run.json", result)
    print(json.dumps(result, indent=2))
    return 0


def _analyze(directory: Path) -> int:
    protocol = load_protocol(directory / "protocol.json")
    raw_path = directory / "raw" / "samples.jsonl"
    samples = tuple(iter_jsonl(raw_path)) if raw_path.is_file() else ()
    analysis = analyze_campaign(
        samples,
        campaign_id=protocol.campaign_id,
        candidate=protocol.candidate,
        baseline=protocol.baseline,
        energy_domain=protocol.energy_domain,
        expected_sessions=protocol.sessions,
        expected_pairs_per_session=protocol.pairs_per_session,
        bootstrap_seed=protocol.bootstrap_seed,
        bootstrap_resamples=protocol.bootstrap_resamples,
    )
    write_json(directory / "analysis.json", analysis)
    print(json.dumps(analysis, indent=2))
    return 0 if analysis["complete_confirmatory_design"] else 2


def _report(directory: Path) -> int:
    analysis = read_json(directory / "analysis.json")
    capabilities = read_json(directory / "capabilities.json")
    (directory / "report.md").write_text(render_report(analysis, capabilities), encoding="utf-8", newline="\n")
    manifest = seal_campaign(directory)
    verification = verify_campaign(directory)
    result = {"terminal_state": analysis["terminal_state"], "manifest": manifest, "verification": verification}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if analysis["terminal_state"] != "BLOCKED_PHYSICAL_INSTRUMENT" else 2


def _rapl_source(capabilities: dict[str, Any]) -> RaplPackageSource | None:
    valid_ids = {
        item["zone_id"] for item in capabilities["rapl"]["validations"]
        if item.get("valid") and item.get("domain") == "CPU_PACKAGE_RAPL"
    }
    for zone in capabilities["rapl"]["zones"]:
        if zone["zone_id"] in valid_ids:
            return RaplPackageSource(Path(zone["energy_uj_path"]), Path(zone["max_energy_range_uj_path"]))
    return None


def _wall_source(capabilities: dict[str, Any]) -> CallbackWallSource | None:
    url = capabilities.get("wall_meter", {}).get("url")
    validation = capabilities.get("wall_meter", {}).get("validation") or {}
    if not url or not validation.get("valid"):
        return None

    def latest() -> tuple[float, float, str]:
        samples = fetch_local_api(url)
        if not samples:
            raise ValueError("local meter API returned no samples")
        item = samples[-1]
        return item.cumulative_joules, item.epoch_seconds, item.device_id

    return CallbackWallSource(latest)


def _blocked_stage(stage: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "status": "BLOCKED_PHYSICAL_INSTRUMENT",
        "stage": stage,
        "reason_codes": reasons,
        "workload_started": False,
        "joules": None,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _default_campaign_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-energy-%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
