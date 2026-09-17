from __future__ import annotations

import unittest

from casulo.t.measurement import (
    calibrate_shared_iterations,
    coefficient_of_variation,
    cpu_topology_snapshot,
    system_telemetry_snapshot,
)


class MeasurementCalibrationTests(unittest.TestCase):
    def test_calibration_uses_shared_maximum_without_speedup_selection(
        self,
    ) -> None:
        per_iteration = {"candidate": 2_000_000, "baseline": 1_000_000}

        def measure(function, iterations):
            backend = function()
            wall = per_iteration[backend] * iterations
            return wall, wall

        selected, audit = calibrate_shared_iterations(
            {
                "candidate": lambda: "candidate",
                "baseline": lambda: "baseline",
            },
            minimum_iterations=1,
            maximum_iterations=16,
            target_wall_ms=8,
            measure=measure,
        )

        self.assertEqual(selected, 8)
        self.assertTrue(audit["all_backends_reached_target"])
        self.assertFalse(audit["uses_speedup_or_winner_selection"])
        self.assertEqual(
            audit["required_iterations_by_backend"],
            {"candidate": 4, "baseline": 8},
        )

    def test_coefficient_of_variation_is_sample_based(self) -> None:
        self.assertAlmostEqual(
            coefficient_of_variation([9.0, 10.0, 11.0]),
            0.1,
        )
        self.assertIsNone(coefficient_of_variation([1.0]))


class MeasurementTelemetryTests(unittest.TestCase):
    def test_telemetry_is_explicit_when_sensors_are_missing(self) -> None:
        snapshot = system_telemetry_snapshot(static=True)

        self.assertIn("temperature_celsius", snapshot)
        self.assertIn("cpu_topology", snapshot)
        self.assertIn("process_cpu_affinity", snapshot)

    def test_topology_never_invents_cores(self) -> None:
        topology = cpu_topology_snapshot()

        self.assertIn("logical_cpu_count", topology)
        self.assertTrue(
            topology["cores"] is not None or topology["reason"] is not None
        )


if __name__ == "__main__":
    unittest.main()
