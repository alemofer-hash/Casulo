from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import statistics
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


HWINFO_SOURCE_SCHEMA = "casulo-energy-hwinfo-source/1.0"
HWINFO_WINDOW_SCHEMA = "casulo-energy-hwinfo-window/1.0"
_UNITS = {"w", "mw", "j", "mj", "wh", "mwh"}
_UNIT_SCALE = {
    "w": 1.0,
    "mw": 1e-3,
    "j": 1.0,
    "mj": 1e-3,
    "wh": 3600.0,
    "mwh": 3.6,
}


class HWiNFOError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Snapshot:
    path: str
    bytes_read: int
    file_size_at_open: int
    mtime_ns: int
    sha256: str
    data: bytes
    complete_bytes: int
    partial_final_line_ignored: bool

    def metadata(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("data")
        return value


@dataclass(frozen=True, slots=True)
class Sensor:
    index: int
    literal_name: str
    normalized_name: str
    kind: str
    unit: str
    si_scale: float
    provenance: str
    session_id: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HWiNFORow:
    session_id: int
    timestamp_local: datetime
    timestamp_utc: datetime
    values: tuple[str, ...]
    line_number: int


@dataclass(frozen=True, slots=True)
class ParsedCSV:
    encoding: str
    bom: str | None
    delimiter: str
    decimal_separator: str
    headers: tuple[tuple[str, ...], ...]
    rows: tuple[HWiNFORow, ...]
    sensors: tuple[Sensor, ...]
    selected_energy_sensor: Sensor | None
    candidate_energy_sensors: tuple[Sensor, ...]
    duplicate_sensor_names: tuple[str, ...]
    incomplete_rows: int
    invalid_rows: int
    duplicate_timestamps: int
    timestamp_regressions: int
    session_count: int
    gaps_seconds: tuple[float, ...]
    first_timestamp_utc: str | None
    last_timestamp_utc: str | None

    def inspection(self) -> dict[str, Any]:
        intervals = _positive_intervals(self.rows)
        return {
            "schema": HWINFO_SOURCE_SCHEMA,
            "encoding": self.encoding,
            "bom": self.bom,
            "delimiter": self.delimiter,
            "decimal_separator": self.decimal_separator,
            "header_count": len(self.headers),
            "column_counts": [len(item) for item in self.headers],
            "complete_rows": len(self.rows),
            "incomplete_rows": self.incomplete_rows,
            "invalid_rows": self.invalid_rows,
            "duplicate_timestamps": self.duplicate_timestamps,
            "timestamp_regressions": self.timestamp_regressions,
            "session_count": self.session_count,
            "first_timestamp_utc": self.first_timestamp_utc,
            "last_timestamp_utc": self.last_timestamp_utc,
            "sampling": {
                "intervals": len(intervals),
                "median_seconds": statistics.median(intervals) if intervals else None,
                "minimum_seconds": min(intervals) if intervals else None,
                "maximum_seconds": max(intervals) if intervals else None,
                "p95_seconds": _percentile(intervals, 0.95) if intervals else None,
                "gaps_over_5x_median": list(self.gaps_seconds),
            },
            "selected_energy_sensor": self.selected_energy_sensor.to_dict() if self.selected_energy_sensor else None,
            "candidate_energy_sensors": [item.to_dict() for item in self.candidate_energy_sensors],
            "duplicate_sensor_names": list(self.duplicate_sensor_names),
            "explicit_estimate": bool(self.selected_energy_sensor and self.selected_energy_sensor.provenance != "hwinfo_reported_cpu_package"),
        }


@dataclass(frozen=True, slots=True)
class IntegratedWindow:
    status: str
    reason_code: str
    sensor: dict[str, Any]
    start_utc: str
    end_utc: str
    first_sample_utc: str | None
    last_sample_utc: str | None
    sample_count: int
    median_interval_seconds: float | None
    maximum_gap_seconds: float | None
    coverage: float
    duration_seconds: float
    energy_joules: float | None
    average_watts: float | None
    source_session_id: int | None
    schema: str = HWINFO_WINDOW_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_shared_snapshot(path: Path, *, maximum_bytes: int = 256 * 1024 * 1024) -> Snapshot:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise HWiNFOError(f"HWiNFO CSV is not a regular file: {source}")
    stat = source.stat()
    if stat.st_size > maximum_bytes:
        raise HWiNFOError("HWiNFO CSV exceeds bounded parser size")
    # CPython's Windows file descriptor opens with sharing compatible with the
    # active HWiNFO logger. Read only the length observed at open.
    with source.open("rb") as handle:
        file_size = min(stat.st_size, maximum_bytes)
        data = handle.read(file_size)
    newline = max(data.rfind(b"\n"), data.rfind(b"\r"))
    if newline < 0:
        complete = 0
    elif data[newline : newline + 2] == b"\r\n":
        complete = newline + 2
    else:
        complete = newline + 1
    partial = complete < len(data) and bool(data[complete:])
    return Snapshot(
        str(source.resolve()), len(data), stat.st_size, stat.st_mtime_ns,
        hashlib.sha256(data).hexdigest(), data, complete, partial,
    )


def parse_snapshot(snapshot: Snapshot, *, local_timezone=None) -> ParsedCSV:
    raw = snapshot.data[: snapshot.complete_bytes]
    encoding, bom = _detect_encoding(raw)
    text = raw.decode(encoding, errors="strict")
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines:
        raise HWiNFOError("HWiNFO CSV has no complete lines")
    delimiter = _detect_delimiter(lines)
    decimal = _detect_decimal_separator(lines, delimiter)
    tz = local_timezone or datetime.now().astimezone().tzinfo
    if tz is None:
        raise HWiNFOError("local timezone is unavailable")
    headers: list[tuple[str, ...]] = []
    sensors: list[Sensor] = []
    rows: list[HWiNFORow] = []
    current_header: tuple[str, ...] | None = None
    session_id = -1
    incomplete = 0
    invalid = 0
    duplicates = 0
    regressions = 0
    previous: datetime | None = None
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    for line_number, row in enumerate(reader, 1):
        if not row or not any(item.strip() for item in row):
            continue
        if _is_header(row):
            session_id += 1
            current_header = tuple(row)
            headers.append(current_header)
            sensors.extend(_sensors_for_header(current_header, session_id))
            previous = None
            continue
        if current_header is None:
            invalid += 1
            continue
        if len(row) < len(current_header):
            incomplete += 1
            continue
        try:
            local = _parse_timestamp(row[0], row[1], tz)
        except (ValueError, IndexError):
            invalid += 1
            continue
        utc = local.astimezone(timezone.utc)
        if previous is not None:
            if utc == previous:
                duplicates += 1
            elif utc < previous:
                regressions += 1
                session_id += 1
                # A timestamp reset without a repeated header is a new logger
                # session using the same structural header.
                current_header = tuple(current_header)
                headers.append(current_header)
                sensors.extend(_sensors_for_header(current_header, session_id))
        rows.append(HWiNFORow(session_id, local, utc, tuple(row[: len(current_header)]), line_number))
        previous = utc
    if not headers:
        raise HWiNFOError("HWiNFO header was not found")
    candidates = tuple(sorted((item for item in sensors if item.kind in {"cumulative_energy", "package_power"}), key=_sensor_priority))
    selected = candidates[0] if candidates else None
    names: dict[str, int] = {}
    for item in sensors:
        names[item.normalized_name] = names.get(item.normalized_name, 0) + 1
    duplicate_names = tuple(sorted(name for name, count in names.items() if count > 1))
    gaps = _gaps(rows)
    return ParsedCSV(
        encoding, bom, delimiter, decimal, tuple(headers), tuple(rows), tuple(sensors),
        selected, candidates, duplicate_names, incomplete, invalid, duplicates,
        regressions, max(0, session_id + 1), gaps,
        rows[0].timestamp_utc.isoformat() if rows else None,
        rows[-1].timestamp_utc.isoformat() if rows else None,
    )


def inspect_file(path: Path) -> tuple[Snapshot, ParsedCSV, dict[str, Any]]:
    snapshot = read_shared_snapshot(path)
    parsed = parse_snapshot(snapshot)
    report = parsed.inspection()
    report["snapshot"] = snapshot.metadata()
    return snapshot, parsed, report


def watch_file(
    path: Path,
    *,
    after_timestamp_utc: str | None = None,
    minimum_new_samples: int = 3,
    timeout_seconds: float = 60.0,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    if minimum_new_samples < 3 or not 1 <= timeout_seconds <= 60:
        raise ValueError("invalid HWiNFO watch bounds")
    started = time.monotonic()
    initial_size = Path(path).stat().st_size
    baseline = datetime.fromisoformat(after_timestamp_utc) if after_timestamp_utc else None
    observations = []
    while time.monotonic() - started <= timeout_seconds:
        snapshot, parsed, _ = inspect_file(path)
        new_rows = [item for item in parsed.rows if baseline is None or item.timestamp_utc > baseline]
        observations.append({
            "observed_monotonic_ns": time.monotonic_ns(),
            "size": snapshot.file_size_at_open,
            "last_timestamp_utc": parsed.last_timestamp_utc,
            "new_samples": len(new_rows),
        })
        valid_values = _sensor_points(parsed, parsed.selected_energy_sensor) if parsed.selected_energy_sensor else ()
        new_values = [item for item in valid_values if baseline is None or item[0] > baseline]
        if len(new_rows) >= minimum_new_samples and len(new_values) >= minimum_new_samples and snapshot.file_size_at_open > initial_size:
            timestamps = [item.timestamp_utc for item in new_rows]
            strict = all(right > left for left, right in zip(timestamps, timestamps[1:]))
            finite = all(math.isfinite(item[1]) and item[1] >= 0 for item in new_values)
            if strict and finite:
                intervals = [(right - left).total_seconds() for left, right in zip(timestamps, timestamps[1:])]
                return {
                    "status": "PASS",
                    "reason_code": "logger_advancing_with_valid_energy_sensor",
                    "new_samples": len(new_rows),
                    "new_energy_samples": len(new_values),
                    "median_interval_seconds": statistics.median(intervals) if intervals else None,
                    "maximum_interval_seconds": max(intervals) if intervals else None,
                    "observations": observations,
                }
        time.sleep(poll_seconds)
    return {
        "status": "BLOCKED",
        "reason_code": "hwinfo_logger_not_advancing",
        "new_samples": 0,
        "new_energy_samples": 0,
        "median_interval_seconds": None,
        "maximum_interval_seconds": None,
        "observations": observations,
    }


def integrate_window(
    parsed: ParsedCSV,
    start_utc: datetime,
    end_utc: datetime,
    *,
    sensor: Sensor | None = None,
    minimum_samples: int = 60,
    minimum_coverage: float = 0.98,
    maximum_gap_factor: float = 5.0,
) -> IntegratedWindow:
    selected = sensor or parsed.selected_energy_sensor
    if selected is None:
        return _invalid_window("energy_sensor_absent", start_utc, end_utc, {})
    if start_utc.tzinfo is None or end_utc.tzinfo is None or end_utc <= start_utc:
        raise HWiNFOError("window timestamps must be aware and advancing")
    points = _sensor_points(parsed, selected)
    sessions = {session for timestamp, _, session in points if start_utc <= timestamp <= end_utc}
    if len(sessions) != 1:
        return _invalid_window("window_crosses_or_lacks_logger_session", start_utc, end_utc, selected.to_dict())
    session = next(iter(sessions))
    series = [(timestamp, value) for timestamp, value, sid in points if sid == session]
    before = [item for item in series if item[0] <= start_utc]
    after = [item for item in series if item[0] >= end_utc]
    if not before or not after:
        return _invalid_window("benchmark_window_not_fully_covered", start_utc, end_utc, selected.to_dict(), session=session)
    internal = [item for item in series if start_utc < item[0] < end_utc]
    first = _interpolate(before[-1], next(item for item in series if item[0] >= start_utc), start_utc)
    last = _interpolate(next(item for item in reversed(series) if item[0] <= end_utc), after[0], end_utc)
    window = [first, *internal, last]
    timestamps = [item[0] for item in window]
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        return _invalid_window("duplicate_or_regressing_timestamp", start_utc, end_utc, selected.to_dict(), session=session)
    values = [item[1] for item in window]
    if any(not math.isfinite(item) or item < 0 for item in values):
        return _invalid_window("negative_or_nonfinite_energy_signal", start_utc, end_utc, selected.to_dict(), session=session)
    intervals = [(right - left).total_seconds() for left, right in zip(timestamps, timestamps[1:])]
    median = statistics.median(intervals) if intervals else None
    maximum_gap = max(intervals) if intervals else None
    duration = (end_utc - start_utc).total_seconds()
    covered = (timestamps[-1] - timestamps[0]).total_seconds()
    coverage = covered / duration if duration > 0 else 0.0
    actual_samples = len(internal) + 2
    if actual_samples < minimum_samples:
        return _invalid_window("insufficient_samples", start_utc, end_utc, selected.to_dict(), samples=actual_samples, median=median, maximum_gap=maximum_gap, coverage=coverage, session=session)
    if coverage < minimum_coverage:
        return _invalid_window("coverage_below_98_percent", start_utc, end_utc, selected.to_dict(), samples=actual_samples, median=median, maximum_gap=maximum_gap, coverage=coverage, session=session)
    if median is None or maximum_gap is None or maximum_gap > maximum_gap_factor * median:
        return _invalid_window("sampling_gap_exceeded", start_utc, end_utc, selected.to_dict(), samples=actual_samples, median=median, maximum_gap=maximum_gap, coverage=coverage, session=session)
    if selected.kind == "package_power":
        energy = sum(((left[1] + right[1]) / 2.0) * (right[0] - left[0]).total_seconds() for left, right in zip(window, window[1:]))
    else:
        energy = values[-1] - values[0]
        if energy < 0:
            return _invalid_window("cumulative_energy_reset_or_unknown_wrap", start_utc, end_utc, selected.to_dict(), samples=actual_samples, median=median, maximum_gap=maximum_gap, coverage=coverage, session=session)
    return IntegratedWindow(
        "PASS", "valid_hwinfo_cpu_package_energy_window", selected.to_dict(),
        start_utc.isoformat(), end_utc.isoformat(), timestamps[0].isoformat(),
        timestamps[-1].isoformat(), actual_samples, median, maximum_gap, coverage,
        duration, energy, energy / duration, session,
    )


def extract_interval_csv(snapshot: Snapshot, start_utc: datetime, end_utc: datetime) -> str:
    parsed = parse_snapshot(snapshot)
    if not parsed.headers:
        raise HWiNFOError("cannot extract without a header")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=parsed.delimiter, lineterminator="\n")
    # Preserve each session's header before its first extracted row.
    emitted: set[int] = set()
    for row in parsed.rows:
        if start_utc <= row.timestamp_utc <= end_utc:
            if row.session_id not in emitted:
                writer.writerow(parsed.headers[min(row.session_id, len(parsed.headers) - 1)])
                emitted.add(row.session_id)
            writer.writerow(row.values)
    return output.getvalue()


def _detect_encoding(raw: bytes) -> tuple[str, str | None]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", "UTF-8"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le", "UTF-16-LE"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be", "UTF-16-BE"
    try:
        raw.decode("utf-8")
        return "utf-8", None
    except UnicodeDecodeError as exc:
        raise HWiNFOError("unsupported or invalid CSV encoding") from exc


def _detect_delimiter(lines: list[str]) -> str:
    first = next((line for line in lines if line.strip()), "")
    counts = {delimiter: first.count(delimiter) for delimiter in (",", ";", "\t")}
    delimiter = max(counts, key=counts.get)
    if counts[delimiter] < 2:
        raise HWiNFOError("CSV delimiter is ambiguous")
    return delimiter


def _detect_decimal_separator(lines: list[str], delimiter: str) -> str:
    for row in csv.reader(io.StringIO("\n".join(lines[1:20])), delimiter=delimiter):
        for value in row[2:]:
            text = value.strip()
            if re.fullmatch(r"[-+]?\d+[.,]\d+", text):
                return "," if "," in text else "."
    return "," if delimiter == ";" else "."


def _is_header(row: list[str]) -> bool:
    return len(row) >= 2 and _normalize(row[0]) in {"date", "data"} and _normalize(row[1]) in {"time", "hora"}


def _sensors_for_header(header: tuple[str, ...], session_id: int) -> tuple[Sensor, ...]:
    result = []
    for index, literal in enumerate(header):
        unit_match = re.search(r"\[\s*([^\]]*)\s*\]\s*$", literal)
        unit = unit_match.group(1).strip().lower() if unit_match else ""
        normalized = _normalize(literal)
        kind = "other"
        provenance = "hwinfo_reported"
        if unit in _UNITS and _is_cpu_package_signal(normalized):
            kind = "cumulative_energy" if unit in {"j", "mj", "wh", "mwh"} and any(word in normalized for word in ("energy", "energia")) else "package_power" if unit in {"w", "mw"} and any(word in normalized for word in ("power", "potencia")) else "other"
            if kind != "other":
                provenance = "hwinfo_explicit_estimate" if any(word in normalized for word in ("estimate", "estimated", "estimada", "estimado")) else "hwinfo_reported_cpu_package"
        result.append(Sensor(index, literal, normalized, kind, unit, _UNIT_SCALE.get(unit, 1.0), provenance, session_id))
    return tuple(result)


def _is_cpu_package_signal(name: str) -> bool:
    excluded = ("limit", "limite", "pl1", "pl2", "pl3", "pl4", "gpu", "gt core", "ia core", "system agent", "restante", "summary", "resumo", "average", "media")
    if any(item in name for item in excluded):
        return False
    exact = (
        "cpu package", "package power", "package energy", "potencia total da cpu",
        "energia total da cpu", "potencia do pacote", "energia do pacote",
    )
    return any(item in name for item in exact)


def _sensor_priority(sensor: Sensor) -> tuple[int, int, int]:
    kind = 0 if sensor.kind == "cumulative_energy" else 1
    provenance = 0 if sensor.provenance == "hwinfo_reported_cpu_package" else 1
    return kind, provenance, sensor.index


def _parse_timestamp(date_text: str, time_text: str, tz) -> datetime:
    text = f"{date_text.strip()} {time_text.strip()}"
    formats = (
        "%d.%m.%Y %H:%M:%S.%f", "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S",
    )
    for pattern in formats:
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError("unsupported HWiNFO timestamp")


def _parse_number(value: str, decimal: str) -> float | None:
    text = value.strip().replace("\u00a0", "")
    if not text:
        return None
    if decimal == ",":
        text = text.replace(".", "").replace(",", ".")
    try:
        result = float(text)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _sensor_points(parsed: ParsedCSV, sensor: Sensor | None) -> tuple[tuple[datetime, float, int], ...]:
    if sensor is None:
        return ()
    points = []
    for row in parsed.rows:
        # Match the equivalent literal in each logger session, not a stale
        # numeric index from a previous header.
        header = parsed.headers[min(row.session_id, len(parsed.headers) - 1)]
        matches = [index for index, name in enumerate(header) if name == sensor.literal_name]
        if len(matches) != 1 or matches[0] >= len(row.values):
            continue
        value = _parse_number(row.values[matches[0]], parsed.decimal_separator)
        if value is not None:
            points.append((row.timestamp_utc, value * sensor.si_scale, row.session_id))
    return tuple(points)


def _positive_intervals(rows: Iterable[HWiNFORow]) -> list[float]:
    result = []
    previous = None
    previous_session = None
    for row in rows:
        if previous is not None and row.session_id == previous_session:
            delta = (row.timestamp_utc - previous).total_seconds()
            if delta > 0:
                result.append(delta)
        previous = row.timestamp_utc
        previous_session = row.session_id
    return result


def _gaps(rows: tuple[HWiNFORow, ...]) -> tuple[float, ...]:
    intervals = _positive_intervals(rows)
    if not intervals:
        return ()
    median = statistics.median(intervals)
    return tuple(item for item in intervals if item > 5 * median)


def _interpolate(left: tuple[datetime, float], right: tuple[datetime, float], target: datetime) -> tuple[datetime, float]:
    if right[0] == left[0]:
        if target != left[0]:
            raise HWiNFOError("cannot interpolate duplicate timestamps")
        return target, left[1]
    fraction = (target - left[0]).total_seconds() / (right[0] - left[0]).total_seconds()
    return target, left[1] + (right[1] - left[1]) * fraction


def _invalid_window(
    reason: str,
    start: datetime,
    end: datetime,
    sensor: dict[str, Any],
    *,
    samples: int = 0,
    median: float | None = None,
    maximum_gap: float | None = None,
    coverage: float = 0.0,
    session: int | None = None,
) -> IntegratedWindow:
    return IntegratedWindow(
        "REJECTED", reason, sensor, start.isoformat(), end.isoformat(), None,
        None, samples, median, maximum_gap, coverage,
        max(0.0, (end - start).total_seconds()), None, None, session,
    )


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction
