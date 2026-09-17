from __future__ import annotations

import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from casulo.livelab.energy_v1.hwinfo import (
    HWiNFOError,
    extract_interval_csv,
    inspect_file,
    integrate_window,
    parse_snapshot,
    read_shared_snapshot,
    watch_file,
)
from casulo.livelab.energy_v1.hwinfo_campaign import HWiNFOIncrementalWatcher, incremental_guard


def _csv(
    rows: list[tuple[str, str, str]],
    *,
    delimiter: str = ",",
    sensor: str = "CPU Package Power [W]",
    bom: bool = False,
    final_newline: bool = True,
) -> bytes:
    header = delimiter.join(("Date", "Time", f'"{sensor}"', '"CPU Package [°C]"', '"Thermal Throttling [Yes/No]"'))
    body = [header]
    for date, stamp, value in rows:
        body.append(delimiter.join((date, stamp, value, "45", "No")))
    text = "\n".join(body) + ("\n" if final_newline else "")
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def _write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def _rows(count: int, *, start_second: int = 0, step: int = 2, value: str = "10.0") -> list[tuple[str, str, str]]:
    return [
        ("07.08.2026", f"12:00:{start_second + index * step:02d}.000", value)
        for index in range(count)
    ]


def test_comma_semicolon_decimal_and_bom(tmp_path: Path) -> None:
    comma = tmp_path / "comma.csv"
    _write(comma, _csv(_rows(3), bom=True))
    _, parsed, report = inspect_file(comma)
    assert report["bom"] == "UTF-8"
    assert parsed.delimiter == ","
    assert parsed.decimal_separator == "."
    assert parsed.selected_energy_sensor is not None
    assert parsed.selected_energy_sensor.literal_name == "CPU Package Power [W]"

    semicolon = tmp_path / "semicolon.csv"
    _write(semicolon, _csv(_rows(3, value="10,5"), delimiter=";"))
    _, parsed, _ = inspect_file(semicolon)
    assert parsed.delimiter == ";"
    assert parsed.decimal_separator == ","


def test_incremental_watcher_reads_only_appended_bytes_and_bounds_partial_line(tmp_path: Path) -> None:
    path = tmp_path / "live.csv"
    initial = _csv(_rows(2, step=1))
    path.write_bytes(initial)
    watcher = HWiNFOIncrementalWatcher(path, maximum_chunk_bytes=4096)
    watcher.initialize()
    assert watcher.bytes_read_total == 0

    partial = b"07.08.2026,12:00:02.000,11.0,46"
    with path.open("ab") as stream:
        stream.write(partial)
    _, values, timestamp, _ = watcher.read_latest()
    assert values[2] == "10.0"
    assert watcher.budget()["partial_bytes"] == len(partial)

    suffix = b",No\n"
    with path.open("ab") as stream:
        stream.write(suffix)
    _, values, timestamp, _ = watcher.read_latest()
    assert values[2:] == ("11.0", "46", "No")
    assert timestamp.microsecond == 0
    assert watcher.bytes_read_total == len(partial) + len(suffix)
    assert watcher.budget()["partial_bytes"] == 0
    state = incremental_guard(watcher)
    assert state["watchdog_reader"] == "append-only-incremental-v1"
    assert state["temperature_c"] == 46.0
    assert state["throttling"] is False


@pytest.mark.parametrize(
    ("sensor", "expected_kind", "scale"),
    [
        ("CPU Package Power [W]", "package_power", 1.0),
        ("CPU Package Power [mW]", "package_power", 1e-3),
        ("CPU Package Energy [J]", "cumulative_energy", 1.0),
        ("CPU Package Energy [mJ]", "cumulative_energy", 1e-3),
        ("CPU Package Energy [Wh]", "cumulative_energy", 3600.0),
        ("CPU Package Energy [mWh]", "cumulative_energy", 3.6),
    ],
)
def test_supported_units(sensor: str, expected_kind: str, scale: float, tmp_path: Path) -> None:
    path = tmp_path / "unit.csv"
    _write(path, _csv(_rows(3), sensor=sensor))
    _, parsed, _ = inspect_file(path)
    assert parsed.selected_energy_sensor is not None
    assert parsed.selected_energy_sensor.kind == expected_kind
    assert parsed.selected_energy_sensor.si_scale == scale


def test_multiple_headers_and_historical_sessions(tmp_path: Path) -> None:
    path = tmp_path / "sessions.csv"
    first = _csv(_rows(3)).decode("utf-8")
    second = _csv(_rows(3, start_second=10)).decode("utf-8")
    _write(path, (first + second).encode("utf-8"))
    snapshot, parsed, report = inspect_file(path)
    assert report["header_count"] == 2
    assert parsed.session_count == 2
    start = parsed.rows[3].timestamp_utc
    end = parsed.rows[-1].timestamp_utc
    extracted = extract_interval_csv(snapshot, start, end)
    assert extracted.count("Date,Time") == 1
    assert "12:00:00.000" not in extracted
    assert "12:00:10.000" in extracted


def test_partial_final_line_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "partial.csv"
    complete = _csv(_rows(3))
    _write(path, complete + b"07.08.2026,12:00:08.000,99")
    snapshot, parsed, _ = inspect_file(path)
    assert snapshot.partial_final_line_ignored
    assert len(parsed.rows) == 3


def test_duplicate_regression_gap_and_sensor_absence(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.csv"
    _write(duplicate, _csv([
        ("07.08.2026", "12:00:00.000", "10"),
        ("07.08.2026", "12:00:00.000", "11"),
        ("07.08.2026", "11:59:59.000", "12"),
    ]))
    _, parsed, _ = inspect_file(duplicate)
    assert parsed.duplicate_timestamps == 1
    assert parsed.timestamp_regressions == 1

    gap = tmp_path / "gap.csv"
    _write(gap, _csv([
        ("07.08.2026", "12:00:00.000", "10"),
        ("07.08.2026", "12:00:02.000", "10"),
        ("07.08.2026", "12:00:30.000", "10"),
    ]))
    _, parsed, report = inspect_file(gap)
    assert report["sampling"]["maximum_seconds"] == 28

    absent = tmp_path / "absent.csv"
    _write(absent, _csv(_rows(3), sensor="Total CPU Utility [%]"))
    _, parsed, _ = inspect_file(absent)
    assert parsed.selected_energy_sensor is None


def test_trapezoidal_integration_and_timestamp_interpolation(tmp_path: Path) -> None:
    path = tmp_path / "power.csv"
    _write(path, _csv([
        ("07.08.2026", "12:00:00.000", "10"),
        ("07.08.2026", "12:00:01.000", "20"),
        ("07.08.2026", "12:00:02.000", "30"),
        ("07.08.2026", "12:00:03.000", "40"),
    ]))
    _, parsed, _ = inspect_file(path)
    start = parsed.rows[0].timestamp_utc + timedelta(seconds=0.5)
    end = parsed.rows[2].timestamp_utc + timedelta(seconds=0.5)
    window = integrate_window(parsed, start, end, minimum_samples=3)
    assert window.status == "PASS"
    # Linear power 15 -> 35 W over two seconds.
    assert window.energy_joules == pytest.approx(50.0)
    assert window.average_watts == pytest.approx(25.0)


@pytest.mark.parametrize(
    ("unit", "values", "expected"),
    [
        ("J", ("100", "130"), 30.0),
        ("mJ", ("1000", "2500"), 1.5),
        ("Wh", ("1", "1.5"), 1800.0),
        ("mWh", ("100", "150"), 180.0),
    ],
)
def test_cumulative_energy_conversion(unit: str, values: tuple[str, str], expected: float, tmp_path: Path) -> None:
    path = tmp_path / "energy.csv"
    _write(path, _csv([
        ("07.08.2026", "12:00:00.000", values[0]),
        ("07.08.2026", "12:00:02.000", values[1]),
    ], sensor=f"CPU Package Energy [{unit}]"))
    _, parsed, _ = inspect_file(path)
    window = integrate_window(parsed, parsed.rows[0].timestamp_utc, parsed.rows[1].timestamp_utc, minimum_samples=2)
    assert window.energy_joules == pytest.approx(expected)


def test_cumulative_reset_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "reset.csv"
    _write(path, _csv([
        ("07.08.2026", "12:00:00.000", "100"),
        ("07.08.2026", "12:00:02.000", "90"),
    ], sensor="CPU Package Energy [J]"))
    _, parsed, _ = inspect_file(path)
    window = integrate_window(parsed, parsed.rows[0].timestamp_utc, parsed.rows[1].timestamp_utc, minimum_samples=2)
    assert window.reason_code == "cumulative_energy_reset_or_unknown_wrap"


def test_window_rejects_insufficient_samples_and_uncovered_bounds(tmp_path: Path) -> None:
    path = tmp_path / "short.csv"
    _write(path, _csv(_rows(3)))
    _, parsed, _ = inspect_file(path)
    start, end = parsed.rows[0].timestamp_utc, parsed.rows[-1].timestamp_utc
    assert integrate_window(parsed, start, end).reason_code == "insufficient_samples"
    assert integrate_window(parsed, start - timedelta(seconds=1), end, minimum_samples=2).reason_code == "benchmark_window_not_fully_covered"


def test_watch_requires_growth_and_three_new_samples(tmp_path: Path) -> None:
    path = tmp_path / "live.csv"
    _write(path, _csv(_rows(2)))
    baseline = parse_snapshot(read_shared_snapshot(path)).rows[-1].timestamp_utc.isoformat()

    def append() -> None:
        time.sleep(0.05)
        with path.open("ab") as handle:
            for second in (4, 6, 8):
                handle.write(f"07.08.2026,12:00:{second:02d}.000,10,45,No\n".encode("utf-8"))
                handle.flush()
                time.sleep(0.05)

    thread = threading.Thread(target=append)
    thread.start()
    result = watch_file(path, after_timestamp_utc=baseline, timeout_seconds=2, poll_seconds=0.02)
    thread.join()
    assert result["status"] == "PASS"
    assert result["new_samples"] >= 3


def test_unknown_encoding_and_missing_header_fail_closed(tmp_path: Path) -> None:
    encoding = tmp_path / "bad.csv"
    _write(encoding, b"\xff\x00\xff\n")
    with pytest.raises((HWiNFOError, UnicodeDecodeError)):
        inspect_file(encoding)
    header = tmp_path / "header.csv"
    _write(header, b"a,b,c\n1,2,3\n")
    with pytest.raises(HWiNFOError, match="header"):
        inspect_file(header)
