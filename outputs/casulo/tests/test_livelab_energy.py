from __future__ import annotations

from pathlib import Path

import pytest

from casulo.livelab.energy import (
    EnergyMeasurementError,
    ExternalMeterSample,
    RaplCounter,
    RaplSample,
    collect_external_meter_validation,
    validate_external_meter,
)


def test_rapl_counter_reads_sysfs_and_computes_regular_delta(tmp_path: Path) -> None:
    energy = tmp_path / "energy_uj"
    maximum = tmp_path / "max_energy_range_uj"
    energy.write_text("100\n", encoding="ascii")
    maximum.write_text("1000\n", encoding="ascii")
    counter = RaplCounter(energy, clock_ns=lambda: 10)
    before = counter.sample()
    energy.write_text("350\n", encoding="ascii")
    counter.clock_ns = lambda: 1_000_000_010
    delta = counter.delta(before, counter.sample())
    assert delta.energy_uj == 250
    assert delta.rollovers == 0
    assert delta.joules == 0.00025
    assert delta.average_watts == 0.00025


def test_rapl_delta_accounts_for_one_rollover() -> None:
    before = RaplSample("package-0", 950, 100, 1000)
    after = RaplSample("package-0", 25, 200, 1000)
    delta = RaplCounter.delta(before, after)
    assert delta.energy_uj == 75
    assert delta.rollovers == 1


def test_rapl_rejects_changed_range_or_nonadvancing_time() -> None:
    with pytest.raises(EnergyMeasurementError, match="range changed"):
        RaplCounter.delta(RaplSample("p", 1, 1, 10), RaplSample("p", 2, 2, 20))
    with pytest.raises(EnergyMeasurementError, match="timestamps"):
        RaplCounter.delta(RaplSample("p", 1, 2, 10), RaplSample("p", 2, 2, 10))


def test_external_meter_requires_advancing_cumulative_energy() -> None:
    frozen = [ExternalMeterSample("meter-a", index, 4.0, 10.0) for index in (1, 2, 3)]
    rejected = validate_external_meter(frozen)
    assert not rejected.valid
    assert rejected.reason_code == "energy_counter_not_advancing"
    accepted = validate_external_meter([
        ExternalMeterSample("meter-a", 1, 4.0, 10.0),
        ExternalMeterSample("meter-a", 2, 4.2, 11.0),
        ExternalMeterSample("meter-a", 3, 4.5, 9.0),
    ])
    assert accepted.valid
    assert accepted.energy_delta_joules == pytest.approx(0.5)


def test_external_meter_rejects_identity_and_counter_regression() -> None:
    identity = validate_external_meter([
        ExternalMeterSample("a", 1, 1),
        ExternalMeterSample("b", 2, 2),
        ExternalMeterSample("b", 3, 3),
    ])
    assert identity.reason_code == "device_identity_changed"
    regression = validate_external_meter([
        ExternalMeterSample("a", 1, 2),
        ExternalMeterSample("a", 2, 1),
        ExternalMeterSample("a", 3, 3),
    ])
    assert regression.reason_code == "energy_counter_regressed"


def test_configured_external_adapter_is_read_and_validated() -> None:
    class Adapter:
        def __init__(self) -> None:
            self.index = 0

        def read_sample(self) -> ExternalMeterSample:
            self.index += 1
            return ExternalMeterSample("usb-meter", self.index, float(self.index))

    samples, result = collect_external_meter_validation(Adapter())
    assert len(samples) == 3
    assert result.valid
    assert result.reason_code == "validated_advancing_counter"
