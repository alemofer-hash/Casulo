from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "os/tools"))
SPEC = importlib.util.spec_from_file_location(
    "run_product_alpha_qemu",
    ROOT / "os/tools/run_product_alpha_qemu.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_serial(tcap_hash: str) -> str:
    return "\n".join((*MODULE.PRODUCT_MARKERS, f"TCAP_HASH_SHA256={tcap_hash}"))


def test_product_native_gate_accepts_only_complete_isolated_tcap_boot() -> None:
    digest = "a" * 64
    result = MODULE.validate_product_boot(
        {"returncode": 33, "timed_out": False, "serial": valid_serial(digest)},
        digest,
    )
    assert result["passed"] is True
    assert result["missing_markers"] == []
    assert result["forbidden_markers"] == []


def test_product_native_gate_rejects_missing_or_fatal_markers() -> None:
    digest = "b" * 64
    serial = valid_serial(digest).replace("TCAP_CODE_RX=PASS\n", "") + "\nCASULO_KERNEL_FATAL"
    result = MODULE.validate_product_boot(
        {"returncode": 33, "timed_out": False, "serial": serial},
        digest,
    )
    assert result["passed"] is False
    assert "TCAP_CODE_RX=PASS" in result["missing_markers"]
    assert result["forbidden_markers"] == ["CASULO_KERNEL_FATAL"]


def test_native_gate_never_contains_performance_or_energy_markers() -> None:
    joined = "\n".join(MODULE.PRODUCT_MARKERS)
    assert "LOSS=" not in joined
    assert "ENERGY" not in joined
    assert "SPEED" not in joined
