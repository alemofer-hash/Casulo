"""Supervisor externo do Thermal Covenant.

Este processo permanece fora do benchmark e encerra somente a árvore do filho
quando um limite selado é alcançado.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .measurement import system_telemetry_snapshot

from .thermal import (
    AutoThermalSource,
    HWiNFOCsvThermalSource,
    JsonFileThermalSource,
    LibreHardwareMonitorSource,
    THERMAL_COVENANT_PROTOCOL,
    THERMAL_GATE_PROTOCOL,
    ThermalCovenantError,
    ThermalPolicy,
    ThermalSource,
    classify_observation,
    classify_power_state,
    thermal_doctor,
)


WATCHDOG_EXIT_BLOCKED = 40
WATCHDOG_EXIT_THERMAL = 41
WATCHDOG_EXIT_THROTTLING = 42
WATCHDOG_EXIT_TIME = 43
WATCHDOG_EXIT_CHILD = 44
WATCHDOG_EXIT_MANUAL = 130


def _write_immutable_json(path: Path, document: Mapping[str, Any]) -> str:
    path = Path(path)
    if path.exists() or path.with_suffix(path.suffix + ".sha256").exists():
        raise ThermalCovenantError(f"evidência térmica já existe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{digest}  {path.name}\n",
        encoding="ascii",
    )
    return digest


def verify_evidence(path: Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    payload = path.read_bytes()
    document = json.loads(payload.decode("utf-8"))
    digest = hashlib.sha256(payload).hexdigest()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    expected = sidecar.read_text(encoding="ascii").split()[0]
    if digest != expected:
        raise ThermalCovenantError(f"SHA-256 térmico diverge: {path}")
    return document, digest


def create_source(
    kind: str,
    *,
    telemetry_file: Path | None = None,
    sensor_url: str | None = None,
    stale_after_seconds: float = 2.0,
) -> ThermalSource:
    if kind == "file":
        if telemetry_file is None:
            raise ThermalCovenantError("--telemetry-file é obrigatório")
        return JsonFileThermalSource(
            telemetry_file,
            stale_after_seconds=stale_after_seconds,
        )
    if kind == "lhm":
        return LibreHardwareMonitorSource(
            sensor_url or "http://127.0.0.1:8085/data.json"
        )
    if kind == "hwinfo-csv":
        if telemetry_file is None:
            raise ThermalCovenantError("--telemetry-file é obrigatório")
        return HWiNFOCsvThermalSource(
            telemetry_file,
            stale_after_seconds=max(5.0, stale_after_seconds),
        )
    if kind == "auto":
        return AutoThermalSource(lhm_url=sensor_url)
    raise ThermalCovenantError(f"fonte térmica desconhecida: {kind}")


def run_supervised(
    command: Sequence[str],
    *,
    source: ThermalSource,
    policy: ThermalPolicy,
    record_path: Path,
    session_id: str,
    max_runtime_seconds: float | None = None,
    cooldown_timeout_seconds: float = 120.0,
    host_snapshot: Callable[[], Mapping[str, Any]] = system_telemetry_snapshot,
) -> tuple[dict[str, Any], int]:
    if not command:
        raise ThermalCovenantError("comando supervisionado está vazio")
    runtime_limit = (
        policy.maximum_continuous_seconds
        if max_runtime_seconds is None
        else float(max_runtime_seconds)
    )
    if not 0 < runtime_limit <= policy.maximum_continuous_seconds:
        raise ThermalCovenantError(
            "runtime precisa respeitar maximum_continuous_seconds"
        )
    if not 0 <= cooldown_timeout_seconds <= 600:
        raise ThermalCovenantError(
            "cooldown_timeout_seconds precisa estar entre 0 e 600"
        )
    host_telemetry_at_start = dict(host_snapshot())
    power_classification = classify_power_state(
        host_telemetry_at_start,
        policy,
    )
    if power_classification.startswith("BLOCKED_"):
        document = _session_document(
            session_id=session_id,
            command=command,
            policy=policy,
            observations=(),
            status="BLOCKED_BEFORE_START",
            child_returncode=None,
            elapsed_seconds=0.0,
            warning_observed=False,
            termination_reason=power_classification,
            host_telemetry_at_start=host_telemetry_at_start,
            host_telemetry_at_end=host_telemetry_at_start,
        )
        _write_immutable_json(record_path, document)
        return document, WATCHDOG_EXIT_BLOCKED
    observations: list[dict[str, Any]] = []
    stable_samples = 0
    cooldown_started = time.monotonic()
    while stable_samples < policy.stable_start_samples:
        observation = source.sample()
        classification = classify_observation(
            observation,
            policy,
            starting=True,
        )
        observations.append(
            {**observation.to_dict(), "classification": classification}
        )
        if classification == "SAFE":
            stable_samples += 1
        elif classification == "WAIT_COOLDOWN":
            stable_samples = 0
            if (
                time.monotonic() - cooldown_started
                < cooldown_timeout_seconds
            ):
                time.sleep(policy.sample_interval_seconds)
                continue
            classification = "COOLDOWN_TIMEOUT"
        else:
            stable_samples = 0
        if classification not in {"SAFE", "WAIT_COOLDOWN"}:
            document = _session_document(
                session_id=session_id,
                command=command,
                policy=policy,
                observations=observations,
                status="BLOCKED_BEFORE_START",
                child_returncode=None,
                elapsed_seconds=0.0,
                warning_observed=classification == "WARNING",
                termination_reason=classification,
                host_telemetry_at_start=host_telemetry_at_start,
                host_telemetry_at_end=dict(host_snapshot()),
            )
            _write_immutable_json(record_path, document)
            return document, WATCHDOG_EXIT_BLOCKED
        if stable_samples < policy.stable_start_samples:
            time.sleep(policy.sample_interval_seconds)

    environment = os.environ.copy()
    environment.update(
        {
            "CASULO_THERMAL_COVENANT": THERMAL_COVENANT_PROTOCOL,
            "OMP_NUM_THREADS": str(policy.maximum_workers),
            "MKL_NUM_THREADS": str(policy.maximum_workers),
            "OPENBLAS_NUM_THREADS": str(policy.maximum_workers),
            "NUMEXPR_NUM_THREADS": str(policy.maximum_workers),
        }
    )
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        list(command),
        env=environment,
        creationflags=creationflags,
    )
    started = time.monotonic()
    status = "RUNNING"
    reason: str | None = None
    warning_observed = False
    exit_code = 0
    try:
        while process.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed >= runtime_limit:
                status = "ABORTED_TIME_BUDGET"
                reason = "MAXIMUM_CONTINUOUS_SECONDS"
                exit_code = WATCHDOG_EXIT_TIME
                _terminate_process_tree(process)
                break
            observation = source.sample()
            classification = classify_observation(observation, policy)
            observations.append(
                {**observation.to_dict(), "classification": classification}
            )
            if classification == "WARNING":
                warning_observed = True
            elif classification == "SOFT_STOP":
                status = "ABORTED_SOFT_TEMPERATURE"
                reason = classification
                exit_code = WATCHDOG_EXIT_THERMAL
                _terminate_process_tree(process)
                break
            elif classification == "ABORT_TEMPERATURE":
                status = "ABORTED_HARD_TEMPERATURE"
                reason = classification
                exit_code = WATCHDOG_EXIT_THERMAL
                _terminate_process_tree(process)
                break
            elif classification == "ABORT_THROTTLING":
                status = "ABORTED_THROTTLING"
                reason = classification
                exit_code = WATCHDOG_EXIT_THROTTLING
                _terminate_process_tree(process)
                break
            elif classification == "BLOCKED_SENSOR":
                status = "ABORTED_SENSOR_LOSS"
                reason = classification
                exit_code = WATCHDOG_EXIT_BLOCKED
                _terminate_process_tree(process)
                break
            time.sleep(policy.sample_interval_seconds)
    except KeyboardInterrupt:
        status = "MANUAL_ABORT"
        reason = "KEYBOARD_INTERRUPT"
        exit_code = WATCHDOG_EXIT_MANUAL
        _terminate_process_tree(process)

    try:
        child_returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        child_returncode = process.wait(timeout=5)
    elapsed = time.monotonic() - started
    if status == "RUNNING":
        if child_returncode != 0:
            status = "CHILD_FAILED"
            reason = f"CHILD_EXIT_{child_returncode}"
            exit_code = WATCHDOG_EXIT_CHILD
        elif warning_observed:
            status = "COMPLETED_WITH_WARNING"
            reason = "WARNING_THRESHOLD_OBSERVED"
            exit_code = WATCHDOG_EXIT_THERMAL
        else:
            status = "PASSED_TELEMETRY"
            reason = None
            exit_code = 0
    document = _session_document(
        session_id=session_id,
        command=command,
        policy=policy,
        observations=observations,
        status=status,
        child_returncode=child_returncode,
        elapsed_seconds=elapsed,
        warning_observed=warning_observed,
        termination_reason=reason,
        host_telemetry_at_start=host_telemetry_at_start,
        host_telemetry_at_end=dict(host_snapshot()),
    )
    _write_immutable_json(record_path, document)
    return document, exit_code


def _session_document(
    *,
    session_id: str,
    command: Sequence[str],
    policy: ThermalPolicy,
    observations: Sequence[Mapping[str, Any]],
    status: str,
    child_returncode: int | None,
    elapsed_seconds: float,
    warning_observed: bool,
    termination_reason: str | None,
    host_telemetry_at_start: Mapping[str, Any],
    host_telemetry_at_end: Mapping[str, Any],
) -> dict[str, Any]:
    temperatures = [
        float(item["temperature_celsius"])
        for item in observations
        if item.get("temperature_celsius") is not None
    ]
    throttling_observed = any(
        item.get("thermal_throttling") is True for item in observations
    )
    all_gate_observable = bool(observations) and all(
        item.get("gate_observable") is True for item in observations
    )
    return {
        "protocol": THERMAL_COVENANT_PROTOCOL,
        "kind": "THERMAL_SESSION",
        "session_id": session_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": policy.to_dict(),
        "command": list(command),
        "status": status,
        "gate_eligible_telemetry": (
            status == "PASSED_TELEMETRY"
            and all_gate_observable
            and not warning_observed
            and not throttling_observed
        ),
        "manual_attestation_required": True,
        "warning_observed": warning_observed,
        "throttling_observed": throttling_observed,
        "all_gate_observable": all_gate_observable,
        "peak_temperature_celsius": max(temperatures) if temperatures else None,
        "child_returncode": child_returncode,
        "elapsed_seconds": elapsed_seconds,
        "termination_reason": termination_reason,
        "host_telemetry_at_start": dict(host_telemetry_at_start),
        "host_telemetry_at_end": dict(host_telemetry_at_end),
        "observations": list(observations),
        "claim": None,
    }


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        process.kill()


def create_attestation(
    session_path: Path,
    *,
    no_odor: bool,
    no_smoke: bool,
    no_abnormal_noise: bool,
) -> tuple[Path, dict[str, Any]]:
    session, session_sha256 = verify_evidence(session_path)
    attestation = {
        "protocol": THERMAL_COVENANT_PROTOCOL,
        "kind": "MANUAL_PHYSICAL_ATTESTATION",
        "session_id": session["session_id"],
        "session_sha256": session_sha256,
        "attested_at_utc": datetime.now(timezone.utc).isoformat(),
        "no_odor": bool(no_odor),
        "no_smoke": bool(no_smoke),
        "no_abnormal_noise": bool(no_abnormal_noise),
        "accepted": bool(no_odor and no_smoke and no_abnormal_noise),
        "claim": None,
    }
    path = Path(session_path).with_suffix(".attestation.json")
    _write_immutable_json(path, attestation)
    return path, attestation


def evaluate_gate(
    session_paths: Sequence[Path],
    *,
    output_path: Path,
    required_sessions: int = 3,
) -> tuple[dict[str, Any], int]:
    sessions: list[dict[str, Any]] = []
    reasons: list[str] = []
    ids: set[str] = set()
    for path in session_paths:
        session, session_sha256 = verify_evidence(path)
        attestation_path = Path(path).with_suffix(".attestation.json")
        try:
            attestation, _ = verify_evidence(attestation_path)
        except (OSError, json.JSONDecodeError, ThermalCovenantError) as exc:
            reasons.append(f"{path}: atestado ausente ou inválido: {exc}")
            continue
        session_id = str(session.get("session_id"))
        if session_id in ids:
            reasons.append(f"sessão duplicada: {session_id}")
            continue
        ids.add(session_id)
        accepted = (
            session.get("gate_eligible_telemetry") is True
            and attestation.get("accepted") is True
            and attestation.get("session_sha256") == session_sha256
        )
        if not accepted:
            reasons.append(f"sessão inelegível: {session_id}")
        sessions.append(
            {
                "session_id": session_id,
                "session_sha256": session_sha256,
                "status": session.get("status"),
                "peak_temperature_celsius": session.get(
                    "peak_temperature_celsius"
                ),
                "telemetry_eligible": session.get(
                    "gate_eligible_telemetry"
                ),
                "physical_attestation_accepted": attestation.get("accepted"),
                "accepted": accepted,
            }
        )
    accepted_count = sum(item["accepted"] for item in sessions)
    if len(ids) < required_sessions:
        reasons.append(
            f"sessões independentes insuficientes: {len(ids)}/{required_sessions}"
        )
    passed = accepted_count >= required_sessions and not reasons
    document = {
        "protocol": THERMAL_GATE_PROTOCOL,
        "kind": "THERMAL_RESUME_GATE",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "required_sessions": required_sessions,
        "accepted_sessions": accepted_count,
        "status": "PASSED" if passed else "BLOCKED",
        "roadmap_may_resume": passed,
        "sessions": sessions,
        "reasons": reasons,
        "claim": None,
    }
    _write_immutable_json(output_path, document)
    return document, 0 if passed else WATCHDOG_EXIT_BLOCKED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casulo-thermal")
    commands = parser.add_subparsers(dest="command_name", required=True)
    doctor = commands.add_parser("doctor")
    _add_source_arguments(doctor)
    doctor.add_argument("--output", type=Path)
    run = commands.add_parser("run")
    _add_source_arguments(run)
    run.add_argument("--record", type=Path, required=True)
    run.add_argument("--session-id", required=True)
    run.add_argument("--max-runtime-seconds", type=float, default=20.0)
    run.add_argument("--cooldown-timeout-seconds", type=float, default=120.0)
    run.add_argument("child_command", nargs=argparse.REMAINDER)
    attest = commands.add_parser("attest")
    attest.add_argument("session", type=Path)
    attest.add_argument("--no-odor", action="store_true", required=True)
    attest.add_argument("--no-smoke", action="store_true", required=True)
    attest.add_argument(
        "--no-abnormal-noise",
        action="store_true",
        required=True,
    )
    gate = commands.add_parser("gate")
    gate.add_argument("sessions", nargs="+", type=Path)
    gate.add_argument("--output", type=Path, required=True)
    gate.add_argument("--required-sessions", type=int, default=3)
    verify = commands.add_parser("verify")
    verify.add_argument("evidence", type=Path)
    return parser


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source",
        choices=("auto", "file", "lhm", "hwinfo-csv"),
        default="auto",
    )
    parser.add_argument("--telemetry-file", type=Path)
    parser.add_argument("--sensor-url")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command_name == "verify":
            document, digest = verify_evidence(args.evidence)
            print(json.dumps({"ok": True, "sha256": digest, "kind": document.get("kind")}, indent=2))
            return 0
        if args.command_name == "attest":
            path, document = create_attestation(
                args.session,
                no_odor=args.no_odor,
                no_smoke=args.no_smoke,
                no_abnormal_noise=args.no_abnormal_noise,
            )
            print(json.dumps({"ok": True, "path": str(path), **document}, ensure_ascii=False, indent=2))
            return 0 if document["accepted"] else WATCHDOG_EXIT_BLOCKED
        if args.command_name == "gate":
            document, exit_code = evaluate_gate(
                args.sessions,
                output_path=args.output,
                required_sessions=args.required_sessions,
            )
            print(json.dumps(document, ensure_ascii=False, indent=2))
            return exit_code
        policy = ThermalPolicy()
        source = create_source(
            args.source,
            telemetry_file=args.telemetry_file,
            sensor_url=args.sensor_url,
            stale_after_seconds=policy.sensor_stale_after_seconds,
        )
        if args.command_name == "doctor":
            document = thermal_doctor(source, policy)
            if args.output:
                _write_immutable_json(args.output, document)
            print(json.dumps(document, ensure_ascii=False, indent=2))
            return 0 if document["performance_ready"] else WATCHDOG_EXIT_BLOCKED
        child_command = list(args.child_command)
        if child_command and child_command[0] == "--":
            child_command = child_command[1:]
        document, exit_code = run_supervised(
            child_command,
            source=source,
            policy=policy,
            record_path=args.record,
            session_id=args.session_id,
            max_runtime_seconds=args.max_runtime_seconds,
            cooldown_timeout_seconds=args.cooldown_timeout_seconds,
        )
        print(json.dumps(document, ensure_ascii=False, indent=2))
        return exit_code
    except (OSError, ValueError, ThermalCovenantError) as exc:
        print(f"casulo-thermal: bloqueado: {exc}", file=sys.stderr)
        return WATCHDOG_EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
