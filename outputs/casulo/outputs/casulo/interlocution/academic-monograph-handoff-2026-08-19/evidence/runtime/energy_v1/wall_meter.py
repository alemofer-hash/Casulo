from __future__ import annotations

import csv
import ipaddress
import json
import math
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class WallMeterSample:
    device_id: str
    timestamp_utc: str
    epoch_seconds: float
    cumulative_joules: float
    watts: float | None
    source_kind: str
    physical: bool
    sequence: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WallMeterValidation:
    valid: bool
    reason_code: str
    samples: int
    advancing_intervals: int
    delta_joules: float | None
    device_id: str | None
    physical: bool
    source_kind: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def import_meter_file(path: Path, *, device_id: str | None = None) -> tuple[WallMeterSample, ...]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"meter export is not a regular file: {source}")
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            records = list(csv.DictReader(handle))
    elif suffix in {".jsonl", ".ndjson"}:
        records = []
        with source.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"meter JSONL line {line_number} is not an object")
                records.append(value)
    else:
        raise ValueError("meter export must be CSV or JSONL")
    return _parse_records(records, device_id=device_id, source_kind=f"physical_export:{suffix[1:]}")


def fetch_local_api(url: str, *, timeout_seconds: float = 2.0) -> tuple[WallMeterSample, ...]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("meter API URL must use HTTP(S)")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.lower() != "localhost":
            raise ValueError("meter API must be loopback or localhost") from None
    else:
        if not address.is_loopback:
            raise ValueError("meter API must be loopback or localhost")
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - loopback restricted
        payload = json.loads(response.read(4 * 1024 * 1024))
    records = payload if isinstance(payload, list) else payload.get("samples") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError("meter API payload must contain a sample list")
    return _parse_records(records, device_id=None, source_kind="physical_local_api")


def mock_samples(values: Iterable[tuple[float, float]], *, device_id: str = "mock") -> tuple[WallMeterSample, ...]:
    result = []
    for index, (epoch, joules) in enumerate(values):
        timestamp = datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
        result.append(WallMeterSample(device_id, timestamp, float(epoch), float(joules), None, "mock", False, index))
    return tuple(result)


def validate_meter_samples(samples: tuple[WallMeterSample, ...]) -> WallMeterValidation:
    if len(samples) < 2:
        return WallMeterValidation(False, "insufficient_samples", len(samples), 0, None, None, False, None)
    first = samples[0]
    if not first.device_id or any(item.device_id != first.device_id for item in samples):
        return WallMeterValidation(False, "device_identity_changed", len(samples), 0, None, None, False, None)
    physical = all(item.physical for item in samples)
    if not physical:
        return WallMeterValidation(False, "simulated_or_mock_source_rejected", len(samples), 0, None, first.device_id, False, first.source_kind)
    advancing = 0
    for left, right in zip(samples, samples[1:]):
        for item in (left, right):
            if not math.isfinite(item.epoch_seconds) or not math.isfinite(item.cumulative_joules) or item.cumulative_joules < 0:
                return WallMeterValidation(False, "invalid_meter_value", len(samples), advancing, None, first.device_id, physical, first.source_kind)
            if item.watts is not None and (not math.isfinite(item.watts) or item.watts < 0):
                return WallMeterValidation(False, "invalid_meter_power", len(samples), advancing, None, first.device_id, physical, first.source_kind)
        if right.epoch_seconds <= left.epoch_seconds:
            return WallMeterValidation(False, "timestamp_not_monotonic", len(samples), advancing, None, first.device_id, physical, first.source_kind)
        if right.cumulative_joules < left.cumulative_joules:
            return WallMeterValidation(False, "energy_counter_regressed", len(samples), advancing, None, first.device_id, physical, first.source_kind)
        if right.cumulative_joules > left.cumulative_joules:
            advancing += 1
    if advancing == 0:
        return WallMeterValidation(False, "energy_counter_not_advancing", len(samples), 0, 0.0, first.device_id, physical, first.source_kind)
    return WallMeterValidation(True, "validated_physical_cumulative_joules", len(samples), advancing, samples[-1].cumulative_joules - samples[0].cumulative_joules, first.device_id, True, first.source_kind)


def align_window(samples: tuple[WallMeterSample, ...], start_epoch: float, end_epoch: float) -> tuple[WallMeterSample, WallMeterSample]:
    if end_epoch <= start_epoch:
        raise ValueError("wall-meter window did not advance")
    before = [item for item in samples if item.epoch_seconds <= start_epoch]
    after = [item for item in samples if item.epoch_seconds >= end_epoch]
    if not before or not after:
        raise ValueError("meter export does not bracket the workload window")
    return before[-1], after[0]


def _parse_records(records: list[dict[str, Any]], *, device_id: str | None, source_kind: str) -> tuple[WallMeterSample, ...]:
    result: list[WallMeterSample] = []
    for index, record in enumerate(records):
        identity = str(device_id or record.get("device_id") or "").strip()
        raw_timestamp = record.get("timestamp_utc", record.get("timestamp", record.get("epoch_seconds")))
        epoch, timestamp = _parse_timestamp(raw_timestamp)
        try:
            joules = float(record["cumulative_joules"])
            watts = None if record.get("watts") in {None, ""} else float(record["watts"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid meter record {index}") from exc
        result.append(WallMeterSample(identity, timestamp, epoch, joules, watts, source_kind, True, index))
    return tuple(result)


def _parse_timestamp(value: Any) -> tuple[float, str]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        if not math.isfinite(epoch):
            raise ValueError("non-finite meter timestamp")
        return epoch, datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("meter timestamp is absent")
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("meter timestamp must include timezone")
    normalized = parsed.astimezone(timezone.utc)
    return normalized.timestamp(), normalized.isoformat()
