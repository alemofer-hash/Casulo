from __future__ import annotations

import importlib.util
from pathlib import Path


def load_qualification_module():
    path = Path(__file__).resolve().parents[1] / "tools" / "qualify_energy_host.py"
    spec = importlib.util.spec_from_file_location("qualify_energy_host", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quiescence_uses_cpu_usage_not_clock_weighted_cpu_utility() -> None:
    module = load_qualification_module()
    header = (
        "Potência total da CPU [W]",
        "Uso total da CPU [%]",
        "Utilização total da CPU [%]",
    )

    sensors = module.sensor_map(header, 0)

    assert sensors["indices"]["total_cpu_usage"] == 1
    assert sensors["indices"]["total_cpu_utility"] == 2
    assert sensors["literal_names"]["total_cpu_usage"] == "Uso total da CPU [%]"
    assert sensors["literal_names"]["total_cpu_utility"] == "Utilização total da CPU [%]"
