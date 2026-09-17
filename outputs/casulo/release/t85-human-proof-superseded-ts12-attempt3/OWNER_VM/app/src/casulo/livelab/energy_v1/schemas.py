from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


PROTOCOL_SCHEMA = "casulo-energy-protocol/1.0"
CAPABILITIES_SCHEMA = "casulo-energy-capabilities/1.0"
ENVIRONMENT_SCHEMA = "casulo-energy-environment/1.0"
SCHEDULE_SCHEMA = "casulo-energy-schedule/1.0"
SAMPLE_SCHEMA = "casulo-energy-sample/1.0"
ANALYSIS_SCHEMA = "casulo-energy-analysis/1.0"
MANIFEST_SCHEMA = "casulo-energy-manifest/1.0"

PHYSICAL_DOMAINS = frozenset({"CPU_PACKAGE_RAPL", "TOTAL_SYSTEM_WALL"})
NON_ENERGY_DOMAINS = frozenset({"BATTERY_DELTA", "LOGICAL_TELEMETRY"})
TERMINAL_STATES = frozenset(
    {
        "PASS_CPU_PACKAGE_ENERGY",
        "PASS_TOTAL_SYSTEM_ENERGY",
        "FAIL_NO_ENERGY_ADVANTAGE",
        "BLOCKED_PHYSICAL_INSTRUMENT",
    }
)


class EnergyProtocolError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True
    ) + "\n"
    destination.write_text(encoded, encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require_finite_nonnegative(value: Any, label: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EnergyProtocolError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise EnergyProtocolError(f"{label} must be finite and nonnegative")
    return result


def validate_sample(sample: Mapping[str, Any]) -> None:
    required = {
        "schema",
        "campaign_id",
        "session_id",
        "pair_id",
        "order_in_pair",
        "implementation",
        "workload",
        "seed",
        "K",
        "timestamp_utc_start",
        "timestamp_utc_end",
        "monotonic_ns_start",
        "monotonic_ns_end",
        "energy_domain",
        "energy_start_joules",
        "energy_end_joules",
        "energy_delta_joules",
        "elapsed_seconds",
        "battery_before",
        "battery_after",
        "temperature",
        "frequency",
        "throttling",
        "equivalence",
        "accepted",
        "reason_code",
        "hashes",
        "physical_measurement",
        "source_provenance",
        "phases_seconds",
        "compilation_included",
    }
    missing = required - set(sample)
    if missing:
        raise EnergyProtocolError(f"sample missing fields: {sorted(missing)}")
    if sample["schema"] != SAMPLE_SCHEMA:
        raise EnergyProtocolError("unexpected sample schema")
    if sample["energy_domain"] not in PHYSICAL_DOMAINS:
        raise EnergyProtocolError("sample has no scientific physical energy domain")
    if sample["physical_measurement"] is not True:
        raise EnergyProtocolError("scientific sample must be physical")
    if not isinstance(sample["K"], int) or isinstance(sample["K"], bool) or sample["K"] < 1:
        raise EnergyProtocolError("K must be a positive integer")
    if sample["monotonic_ns_end"] <= sample["monotonic_ns_start"]:
        raise EnergyProtocolError("sample monotonic interval did not advance")
    for field in ("energy_start_joules", "energy_end_joules", "energy_delta_joules", "elapsed_seconds"):
        require_finite_nonnegative(sample[field], field)
    if sample["energy_end_joules"] < sample["energy_start_joules"]:
        raise EnergyProtocolError("cumulative energy regressed")
    expected = sample["energy_end_joules"] - sample["energy_start_joules"]
    tolerance = max(1e-9, abs(float(sample["energy_delta_joules"])) * 1e-9)
    if abs(expected - float(sample["energy_delta_joules"])) > tolerance:
        raise EnergyProtocolError("energy delta differs from cumulative endpoints")
    if sample["accepted"] is True and sample["reason_code"] != "accepted":
        raise EnergyProtocolError("accepted sample has a rejection reason")
    if sample["accepted"] is False and not sample["reason_code"]:
        raise EnergyProtocolError("rejected sample lacks a reason")
    hashes = sample["hashes"]
    if not isinstance(hashes, Mapping):
        raise EnergyProtocolError("hashes must be an object")
    for name in ("executable", "tcap", "dataset", "configuration"):
        value = hashes.get(name)
        if value is not None and (
            not isinstance(value, str)
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
        ):
            raise EnergyProtocolError(f"invalid {name} SHA-256")


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EnergyProtocolError(f"invalid JSONL at line {line_number}") from exc
            if not isinstance(value, dict):
                raise EnergyProtocolError(f"JSONL line {line_number} is not an object")
            yield value
