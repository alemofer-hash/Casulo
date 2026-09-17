from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tools.finalize_definitive_energy_block import _thermal_stability


HEADERS = (
    "Date",
    "Time",
    "Temperaturas centrais (avg) [°C]",
    "Estrangulamento térmico do núcleo (avg) [Yes/No]",
)


def _rows(temperatures: list[float], throttled: set[int] | None = None):
    origin = datetime(2026, 8, 8, tzinfo=timezone.utc)
    throttled = throttled or set()
    return [
        SimpleNamespace(
            timestamp_utc=origin + timedelta(seconds=index),
            values=("", "", str(value), "Sim" if index in throttled else "Não"),
        )
        for index, value in enumerate(temperatures)
    ]


def test_idle_throttle_fails_even_when_temperature_is_low() -> None:
    result = _thermal_stability(_rows([50.0] * 40, {10}), HEADERS, 60.0)
    assert result["gate"] == "FAIL"
    assert result["throttle_event_count"] == 1
    assert result["throttle_events"][0]["temperature_c"] == 50.0
    assert "Estrangulamento térmico" in result["throttle_events"][0]["active_instantaneous_columns"][0]


def test_symmetric_thirty_second_band_passes_without_throttle() -> None:
    result = _thermal_stability(_rows([50.0, 51.0] * 16), HEADERS, 60.0)
    assert result["gate"] == "PASS"
    assert result["longest_symmetric_stability_band_seconds"] >= 30.0
    assert result["throttle_event_count"] == 0
