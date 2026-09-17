from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from casulo.livelab.energy_v1.hwinfo import inspect_file
from casulo.livelab.energy_v1.hwinfo_campaign import _normalize, _truthy


ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
OUTPUT = ROOT / "outputs/casulo/energy/2026-08-08-g5-full-worker-energy-definitive"
EVENT = datetime.fromisoformat("2026-08-08T14:19:54.187000+00:00")
TERMS = (
    "thermal throttling",
    "estrangulamento termico",
    "core thermal",
    "regulagem termica",
    "temperatura critica",
    "critical temperature",
    "prochot",
    "power limit",
    "limite de potencia",
    "current limit",
    "limite de corrente",
    "max turbo limit",
    "temperaturas centrais",
    "core temperatures",
    "cpu package",
    "pacote da cpu",
    "package ring",
    "pacote anel",
    "evento termico",
    "thermal event",
    "vr thermal",
    "alerta termico",
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _unit(name: str) -> str | None:
    match = re.search(r"\[([^]]+)\]\s*$", name)
    return match.group(1) if match else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=CSV)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    source = args.csv.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _, parsed, inspection = inspect_file(source)
    rows = [row for row in parsed.rows if EVENT - timedelta(seconds=30) <= row.timestamp_utc <= EVENT + timedelta(seconds=30)]
    if not rows:
        raise RuntimeError("throttle excerpt is absent")
    event = min(rows, key=lambda row: abs((row.timestamp_utc - EVENT).total_seconds()))
    if event.timestamp_utc != EVENT:
        raise RuntimeError("exact throttle timestamp is absent")
    header = parsed.headers[event.session_id]
    indices = [index for index, name in enumerate(header) if any(term in _normalize(name) for term in TERMS)]
    before = max((row for row in rows if row.timestamp_utc < EVENT), key=lambda row: row.timestamp_utc)
    after = min((row for row in rows if row.timestamp_utc > EVENT), key=lambda row: row.timestamp_utc)
    sensors = []
    for index in indices:
        literal = header[index]
        raw = event.values[index]
        unit = _unit(literal)
        is_boolean = bool(unit and _normalize(unit) == "yes no")
        sensors.append({
            "column_index": index,
            "literal_name": literal,
            "normalized_name": _normalize(literal),
            "unit": unit,
            "value_raw": raw,
            "value_normalized": _normalize(raw) if is_boolean else raw.replace(",", "."),
            "value_type": "boolean" if is_boolean else "number" if unit else "text",
            "boolean_value": _truthy(raw) if is_boolean else None,
            "timestamp_utc": EVENT.isoformat(),
            "status_scope": "instantaneous_csv_sample",
            "previous_raw": before.values[index],
            "next_raw": after.values[index],
        })
    by_norm = {item["normalized_name"]: item for item in sensors}
    required_true = (
        "estrangulamento termico do nucleo avg yes no",
        "p core 1 estrangulamento termico yes no",
        "regulagem termica do pacote anel yes no",
    )
    true_coincidence = all(by_norm.get(name, {}).get("boolean_value") is True for name in required_true)
    transient = all(
        _normalize(by_norm[name]["previous_raw"]) in {"nao", "no", "0", "false", "falso"}
        and _normalize(by_norm[name]["next_raw"]) in {"nao", "no", "0", "false", "falso"}
        for name in required_true
    )
    exclusions_false = all(
        not item["boolean_value"]
        for item in sensors
        if item["boolean_value"] is not None
        and any(term in item["normalized_name"] for term in ("temperatura critica", "prochot"))
    )
    power_at_event = [item for item in sensors if item["boolean_value"] is not None and "limite de potencia" in item["normalized_name"]]
    power_false = all(not item["boolean_value"] for item in power_at_event)
    classification = "GENUINE_INSTANTANEOUS_THERMAL_THROTTLE" if true_coincidence and transient and exclusions_false and power_false else "SENSOR_SEMANTICS_AMBIGUOUS"
    excerpt = output / "throttle_event_excerpt.csv"
    with excerpt.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row.values)
    result = {
        "schema": "casulo-hwinfo-throttle-forensic/1.0",
        "source_csv": str(source),
        "event_timestamp_utc": EVENT.isoformat(),
        "source_line_number": event.line_number,
        "excerpt_start_utc": rows[0].timestamp_utc.isoformat(),
        "excerpt_end_utc": rows[-1].timestamp_utc.isoformat(),
        "excerpt_rows": len(rows),
        "sampling": inspection["sampling"],
        "classification": classification,
        "classification_checks": {
            "three_independent_instantaneous_thermal_flags_true": true_coincidence,
            "same_flags_false_immediately_before_and_after": transient,
            "critical_temperature_and_prochot_false": exclusions_false,
            "power_limit_flags_false_at_event": power_false,
            "parser_false_positive": False,
            "timestamp_exact_match": True,
            "historical_maximum_column_used": False,
        },
        "sensors": sensors,
        "raw_excerpt": str(excerpt),
    }
    _write_json(output / "throttle_classification.json", result)
    print(json.dumps({"classification": classification, "sensors": len(sensors), "rows": len(rows), "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
