from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

from casulo.product.pleasant_interface import (
    MAX_UX_EVENT_BYTES,
    UX_EVENT_SCHEMA,
    UxEventKind,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "schemas/product/hosted-native-ux-contract-v1.json"
NATIVE = ROOT / "os/kernel/src/product_runtime.rs"
sys.path.insert(0, str(ROOT / "os/tools"))
SPEC = importlib.util.spec_from_file_location(
    "run_product_alpha_qemu_arc10",
    ROOT / "os/tools/run_product_alpha_qemu.py",
)
assert SPEC and SPEC.loader
QEMU_GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QEMU_GATE)


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _rust_string_array(source: str, name: str) -> list[str]:
    match = re.search(
        rf"pub const {name}: \[&str; \d+\] = \[(.*?)\];",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    return re.findall(r'"([A-Z_]+)"', match.group(1))


def test_hosted_wire_contract_matches_shared_manifest() -> None:
    contract = _contract()
    assert contract["wire_schema"] == UX_EVENT_SCHEMA
    assert contract["max_event_bytes"] == MAX_UX_EVENT_BYTES
    assert contract["event_kinds"] == [kind.value for kind in UxEventKind]
    assert contract["forbidden_progress_fields"] == [
        "progress_percent",
        "percentage",
        "eta",
        "fake_progress",
    ]


def test_native_contract_is_pinned_to_same_bytes_and_surface() -> None:
    contract = _contract()
    source = NATIVE.read_text(encoding="utf-8")
    digest = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    assert f'pub const CONTRACT_SHA256: &str =\n    "{digest}";' in source
    assert f'pub const WIRE_SCHEMA: &str = "{contract["wire_schema"]}";' in source
    assert _rust_string_array(source, "CONTRACT_EVENT_KINDS") == contract["event_kinds"]
    assert _rust_string_array(source, "CONTRACT_PRIORITIES") == contract["priorities"]


def test_native_gate_requires_arc10_markers_without_research_metrics() -> None:
    joined = "\n".join(QEMU_GATE.PRODUCT_MARKERS)
    assert "CASULO_NATIVE_UX_CONTRACT_GATE=PASS" in joined
    assert "CASULO_NATIVE_PRESENCE_PRIORITY=PASS" in joined
    assert "CASULO_NATIVE_LATE_COMPLETION_REJECTED=PASS" in joined
    assert "ENERGY" not in joined
    assert "SPEED" not in joined
    assert "LOSS=" not in joined


def test_native_source_keeps_hosted_adapters_outside_kernel_claim() -> None:
    source = (ROOT / "os/kernel/src/main.rs").read_text(encoding="utf-8")
    assert "CASULO_HOSTED_ONLY_ADAPTERS=physical-audio,dpapi-memory,general-creation-renderer,general-materializer" in source
    assert (
        "CASULO_NATIVE_PRODUCT_ADAPTERS=timer,serial,framebuffer,ramdisk,"
        "system-pack,tcap,scene-projector,gop-renderer,native-model,token-policy,"
        "bounded-creation-compiler,bounded-materializer"
    ) in source
    assert '"NOT_EXECUTED"' in source
    assert "native-physical-audio" not in source


def test_missing_arc10_marker_fails_product_boot() -> None:
    digest = "c" * 64
    serial = "\n".join((*QEMU_GATE.PRODUCT_MARKERS, f"TCAP_HASH_SHA256={digest}"))
    serial = serial.replace("CASULO_NATIVE_ASSISTANT_STREAM=PASS\n", "")
    result = QEMU_GATE.validate_product_boot(
        {"returncode": 33, "timed_out": False, "serial": serial}, digest
    )
    assert result["passed"] is False
    assert result["missing_markers"] == ["CASULO_NATIVE_ASSISTANT_STREAM=PASS"]
