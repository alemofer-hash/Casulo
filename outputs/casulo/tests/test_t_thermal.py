from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from casulo.t.thermal import (
    HWiNFOCsvThermalSource,
    JsonFileThermalSource,
    SequenceThermalSource,
    ThermalPolicy,
    classify_observation,
    classify_power_state,
    thermal_doctor,
)
from casulo.t.thermal_watchdog import (
    WATCHDOG_EXIT_BLOCKED,
    create_attestation,
    evaluate_gate,
    run_supervised,
    verify_evidence,
)


class ThermalCovenantTests(unittest.TestCase):
    @staticmethod
    def powered_host() -> dict[str, object]:
        return {
            "battery_percent": 100.0,
            "power_plugged": True,
        }

    def test_doctor_fails_closed_without_real_sensor(self) -> None:
        source = SequenceThermalSource([40.0], test_trusted=False)

        document = thermal_doctor(source, ThermalPolicy())

        self.assertFalse(document["performance_ready"])
        self.assertEqual(document["classification"], "BLOCKED_SENSOR")

    def test_json_source_requires_fresh_explicit_trust(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "sensor.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "temperature_celsius": 49.5,
                        "temperature_source": "hardware-helper",
                        "temperature_trusted": True,
                        "thermal_throttling": False,
                        "throttling_source": "hardware-helper",
                        "throttling_trusted": True,
                    }
                ),
                encoding="utf-8",
            )

            observation = JsonFileThermalSource(snapshot).sample()

        self.assertTrue(observation.gate_observable)
        self.assertEqual(
            classify_observation(observation, ThermalPolicy(), starting=True),
            "SAFE",
        )

    def test_hwinfo_csv_reads_portuguese_cpu_and_throttling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "sensors.csv"
            log.write_text(
                '"Data","Hora","CPU Inteira [°C]",'
                '"Distância do núcleo para TjMAX [°C]",'
                '"Estrangulamento térmico do núcleo",'
                '"Limite de potência do núcleo",'
                '"GPU Core Temperatura [°C]"\n'
                '"31.07.2026","15:00:00.000","55.0",'
                '"45.0","Não","Sim","70.0"\n',
                encoding="utf-8-sig",
            )

            observation = HWiNFOCsvThermalSource(log).sample()

        self.assertTrue(observation.gate_observable)
        self.assertEqual(observation.temperature_celsius, 55.0)
        self.assertFalse(observation.thermal_throttling)
        self.assertIn('"power_limit_active": true', observation.detail or "")

    def test_external_watchdog_records_light_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            record = Path(temporary) / "session.json"
            document, exit_code = run_supervised(
                [sys.executable, "-c", "pass"],
                source=SequenceThermalSource(
                    [45.0],
                    throttling=[False],
                    test_trusted=True,
                ),
                policy=ThermalPolicy(
                    sample_interval_seconds=0.1,
                    sensor_stale_after_seconds=0.2,
                ),
                record_path=record,
                session_id="unit-light",
                max_runtime_seconds=1.0,
                host_snapshot=self.powered_host,
            )

            verified, _ = verify_evidence(record)
            raw_sha256 = hashlib.sha256(record.read_bytes()).hexdigest()
            sidecar_sha256 = record.with_suffix(
                ".json.sha256"
            ).read_text(encoding="ascii").split()[0]

        self.assertEqual(exit_code, 0)
        self.assertEqual(document["status"], "PASSED_TELEMETRY")
        self.assertTrue(verified["gate_eligible_telemetry"])
        self.assertEqual(raw_sha256, sidecar_sha256)

    def test_watchdog_waits_for_three_cool_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            record = Path(temporary) / "session.json"
            document, exit_code = run_supervised(
                [sys.executable, "-c", "pass"],
                source=SequenceThermalSource(
                    [59.0, 54.0, 54.0, 54.0],
                    throttling=[False],
                    test_trusted=True,
                ),
                policy=ThermalPolicy(
                    sample_interval_seconds=0.1,
                    sensor_stale_after_seconds=0.2,
                ),
                record_path=record,
                session_id="unit-cooldown",
                max_runtime_seconds=1.0,
                cooldown_timeout_seconds=2.0,
                host_snapshot=self.powered_host,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(document["status"], "PASSED_TELEMETRY")
        self.assertEqual(
            [item["classification"] for item in document["observations"][:4]],
            ["WAIT_COOLDOWN", "SAFE", "SAFE", "SAFE"],
        )

    def test_gate_needs_three_attested_independent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions: list[Path] = []
            for index in range(3):
                path = root / f"session-{index}.json"
                run_supervised(
                    [sys.executable, "-c", "pass"],
                    source=SequenceThermalSource(
                        [45.0],
                        throttling=[False],
                        test_trusted=True,
                    ),
                    policy=ThermalPolicy(
                        sample_interval_seconds=0.1,
                        sensor_stale_after_seconds=0.2,
                    ),
                    record_path=path,
                    session_id=f"unit-{index}",
                    max_runtime_seconds=1.0,
                    host_snapshot=self.powered_host,
                )
                create_attestation(
                    path,
                    no_odor=True,
                    no_smoke=True,
                    no_abnormal_noise=True,
                )
                sessions.append(path)

            document, exit_code = evaluate_gate(
                sessions,
                output_path=root / "gate.json",
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(document["status"], "PASSED")
        self.assertTrue(document["roadmap_may_resume"])

    def test_gate_blocks_unattested_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = root / "session.json"
            run_supervised(
                [sys.executable, "-c", "pass"],
                source=SequenceThermalSource(
                    [45.0],
                    throttling=[False],
                    test_trusted=True,
                ),
                policy=ThermalPolicy(
                    sample_interval_seconds=0.1,
                    sensor_stale_after_seconds=0.2,
                ),
                record_path=record,
                session_id="unit-unattested",
                max_runtime_seconds=1.0,
                host_snapshot=self.powered_host,
            )

            document, exit_code = evaluate_gate(
                [record],
                output_path=root / "gate.json",
            )

        self.assertEqual(exit_code, WATCHDOG_EXIT_BLOCKED)
        self.assertEqual(document["status"], "BLOCKED")

    def test_low_unplugged_battery_is_blocked(self) -> None:
        classification = classify_power_state(
            {"battery_percent": 15.0, "power_plugged": False},
            ThermalPolicy(),
        )

        self.assertEqual(classification, "BLOCKED_LOW_BATTERY")


if __name__ == "__main__":
    unittest.main()
