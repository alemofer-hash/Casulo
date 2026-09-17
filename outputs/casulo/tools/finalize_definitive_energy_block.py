"""Seal a fail-closed definitive campaign blocked before any workload."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from casulo.livelab.energy_v1.hwinfo import _normalize, inspect_file
from casulo.livelab.energy_v1.hwinfo_campaign import _truthy


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: str) -> float | None:
    try:
        return float(value.strip().replace(",", "."))
    except ValueError:
        return None


def _thermal_stability(rows: list[Any], headers: tuple[str, ...], ceiling_c: float) -> dict[str, Any]:
    normalized = [_normalize(item) for item in headers]
    temperature_index = next(
        index for index, name in enumerate(normalized) if "temperaturas centrais" in name
    )
    throttle_indices = [
        index
        for index, name in enumerate(normalized)
        if ("estrangulamento termico" in name or "thermal throttling" in name)
        and "maximum" not in name
        and "maximo" not in name
    ]
    values: list[tuple[datetime, float, bool, list[str]]] = []
    for row in rows:
        temperature = _number(row.values[temperature_index])
        if temperature is None:
            continue
        active = [headers[index] for index in throttle_indices if _truthy(row.values[index])]
        values.append(
            (
                row.timestamp_utc,
                temperature,
                bool(active),
                active,
            )
        )
    anchor: float | None = None
    start: datetime | None = None
    longest = 0.0
    longest_start: datetime | None = None
    longest_end: datetime | None = None
    for stamp, temperature, throttling, _ in values:
        if anchor is None and temperature <= ceiling_c and not throttling:
            anchor, start = temperature, stamp
        if (
            anchor is None
            or start is None
            or throttling
            or abs(temperature - anchor) > 1.0
        ):
            anchor, start = None, None
            continue
        duration = (stamp - start).total_seconds()
        if duration > longest:
            longest = duration
            longest_start, longest_end = start, stamp
    temperatures = [item[1] for item in values]
    throttle_events = [item for item in values if item[2]]
    intervals = [
        (current[0] - previous[0]).total_seconds()
        for previous, current in zip(values, values[1:])
    ]
    median_interval = statistics.median(intervals) if intervals else None
    ordered_intervals = sorted(intervals)
    p95_interval = (
        ordered_intervals[max(0, math.ceil(0.95 * len(ordered_intervals)) - 1)]
        if ordered_intervals
        else None
    )
    return {
        "samples": len(values),
        "temperature_c": {
            "minimum": min(temperatures) if temperatures else None,
            "median": statistics.median(temperatures) if temperatures else None,
            "maximum": max(temperatures) if temperatures else None,
            "initial": temperatures[0] if temperatures else None,
            "final": temperatures[-1] if temperatures else None,
        },
        "throttle_event_count": len(throttle_events),
        "throttle_events": [
            {
                "timestamp_utc": item[0].isoformat(),
                "temperature_c": item[1],
                "active_instantaneous_columns": item[3],
            }
            for item in throttle_events
        ],
        "sampling": {
            "intervals": len(intervals),
            "median_seconds": median_interval,
            "p95_seconds": p95_interval,
            "maximum_seconds": max(intervals) if intervals else None,
            "gaps_over_5x_median": [
                value
                for value in intervals
                if median_interval is not None and value > 5 * median_interval
            ],
        },
        "longest_symmetric_stability_band_seconds": longest,
        "longest_stability_start_utc": longest_start.isoformat() if longest_start else None,
        "longest_stability_end_utc": longest_end.isoformat() if longest_end else None,
        "required_stability_seconds": 30.0,
        "stability_band_tolerance_c": 1.0,
        "initial_ceiling_c": ceiling_c,
        "gate": "PASS" if longest >= 30.0 and not throttle_events else "FAIL",
    }


def _extract(rows: list[Any], parsed: Any, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        previous_session = None
        for row in rows:
            if row.session_id != previous_session:
                writer.writerow(parsed.headers[row.session_id])
                previous_session = row.session_id
            writer.writerow(row.values)


def _seal(directory: Path, state: str) -> None:
    excluded = {"MANIFEST.json", "SHA256SUMS"}
    files = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.name not in excluded):
        files.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    _write_json(
        directory / "MANIFEST.json",
        {
            "schema": "casulo-definitive-energy-manifest/1.0",
            "campaign_id": directory.name,
            "terminal_state": state,
            "files": files,
        },
    )
    lines = [f"{item['sha256']}  {item['path']}" for item in files]
    lines.append(f"{_sha256(directory / 'MANIFEST.json')}  MANIFEST.json")
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-utc", required=True)
    parser.add_argument("--end-utc")
    args = parser.parse_args()
    csv_path = args.csv.resolve(strict=True)
    directory = args.output.resolve()
    start = datetime.fromisoformat(args.start_utc)
    end = datetime.fromisoformat(args.end_utc) if args.end_utc else datetime.now(timezone.utc)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timestamps must include UTC offsets")
    _, parsed, inspection = inspect_file(csv_path)
    rows = [row for row in parsed.rows if start <= row.timestamp_utc <= end]
    if not rows:
        raise RuntimeError("no HWiNFO rows overlap the blocked control interval")
    stability = _thermal_stability(rows, parsed.headers[rows[0].session_id], 60.0)
    if stability["gate"] != "FAIL":
        raise RuntimeError("block finalizer refused: thermal stability gate is not failed")
    state = "BLOCKED_PHYSICAL_COOLING_REQUIRED"
    for name in ("raw", "rejected", "equivalence", "receipts"):
        (directory / name).mkdir(parents=True, exist_ok=True)
    _extract(rows, parsed, directory / "raw" / "failed_idle_stability_segment.csv")
    schedule = {
        "schema": "casulo-definitive-energy-schedule/1.0",
        "seed": 20260808,
        "pairs": [
            {
                "pair_id": index,
                "order": ["tcap-full", "pytorch-eager-full"] if index % 2 else ["pytorch-eager-full", "tcap-full"],
            }
            for index in range(1, 22)
        ],
        "activated": False,
    }
    frozen = {
        "schema": "casulo-definitive-energy-frozen-configuration/1.0",
        "campaign_id": directory.name,
        "source_scope": "HWiNFO-reported CPU package energy on bare-metal Windows",
        "sensor": inspection.get("selected_energy_sensor"),
        "polling": inspection.get("sampling"),
        "thermal_hard_ceiling_c": 90.0,
        "initial_idle_ceiling_c": 60.0,
        "matched_start_tolerance_c": 1.0,
        "stability_seconds": 30.0,
        "K_TCAP": None,
        "K_Eager": None,
        "pair_count": 21,
        "schedule_seed": 20260808,
        "bootstrap_seed": 20260808,
        "bootstrap_resamples": 20000,
        "not_frozen_reason": "idle thermal stability gate failed before probes and K calibration",
    }
    frozen_hash = hashlib.sha256(
        json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    frozen["configuration_sha256"] = frozen_hash
    protocol = {
        "schema": "casulo-definitive-energy-protocol/1.0",
        "campaign_id": directory.name,
        "terminal_state": state,
        "sensor": inspection.get("selected_energy_sensor"),
        "source_csv": str(csv_path),
        "blocked_interval": {"start_utc": start.isoformat(), "end_utc": end.isoformat()},
        "workload_started": False,
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    analysis = {
        "schema": "casulo-definitive-energy-analysis/1.0",
        "terminal_state": state,
        "cause": "the bare-metal host could not sustain the pre-registered 30-second thermal stability condition and emitted instantaneous core throttling while idle; a prior independent thermal throttle is also confirmed",
        "throttle_event_classification": "GENUINE_INSTANTANEOUS_THERMAL_THROTTLE",
        "idle_stability": stability,
        "controls_completed": 0,
        "probes_completed": 0,
        "K_TCAP": None,
        "K_Eager": None,
        "valid_pairs": 0,
        "rejected_pair_attempts": 0,
        "complete_trainings_measured": 0,
        "tcap_joules_per_training": None,
        "eager_joules_per_training": None,
        "ratio_tcap_over_eager": None,
        "paired_bootstrap_ci95": None,
        "sign_test": None,
        "numerical_equivalence": "PASS_FROM_FULL_WORKER_GATE_NOT_REMEASURED_FOR_ENERGY",
        "work_unit": {
            "records_per_epoch": 1024,
            "epochs": 400,
            "records_visited": 409600,
            "forward_epochs": 400,
            "backward_epochs": 400,
            "optimizer_steps": 400,
            "parameter_writes": 32400,
        },
        "limitations": {
            "TOTAL_SYSTEM_WALL": "BLOCKED_PHYSICAL_INSTRUMENT",
            "CASULO_NATIVE_ENERGY": "BLOCKED_PHYSICAL_INSTRUMENT",
        },
        "single_physical_action": "provide active cooling and a quiescent host that can sustain the frozen 30-second idle stability gate, then rerun under a new campaign ID",
    }
    _write_json(directory / "protocol.json", protocol)
    _write_json(directory / "frozen_configuration.json", frozen)
    _write_json(directory / "idle_controls.json", {"status": "BLOCKED_BEFORE_CONTROL_A", "stability": stability})
    _write_json(directory / "probes.json", {"status": "NOT_RUN", "reason": state})
    _write_json(directory / "calibration.json", {"status": "NOT_RUN", "K_TCAP": None, "K_Eager": None})
    _write_json(directory / "schedule.json", schedule)
    _write_json(directory / "receipt_chain.json", {"status": "NOT_CREATED", "receipts": 0})
    _write_json(directory / "analysis.json", analysis)
    (directory / "markers.jsonl").write_text("", encoding="utf-8")
    report = f"""# Energia TCAP completo × PyTorch Eager completo

**Estado científico:** `{state}`

A campanha parou antes de qualquer workload. O host não sustentou a condição
idle simétrica pré-registrada de 30 segundos dentro de uma faixa de ±1 °C.
O maior trecho observado foi {stability['longest_symmetric_stability_band_seconds']:.3f} s.
Além disso, o HWiNFO registrou {stability['throttle_event_count']} amostras
instantâneas de throttling do núcleo/P-core 1 durante esse idle sem workload.

O evento anterior a 68 °C foi confirmado como thermal throttling instantâneo
por três sensores HWiNFO. Como o gate térmico falhou antes dos probes, `K` não
foi calibrado e nenhum dos 21 pares foi iniciado. Não existem joules
comparativos válidos para TCAP ou Eager nesta campanha.

## Próxima ação física única

Fornecer resfriamento ativo e um host quiescente capaz de sustentar o gate idle
de 30 segundos; depois executar uma nova identidade de campanha.

`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`

`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`
"""
    (directory / "report.md").write_text(report, encoding="utf-8", newline="\n")
    _seal(directory, state)
    print(json.dumps(analysis, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
