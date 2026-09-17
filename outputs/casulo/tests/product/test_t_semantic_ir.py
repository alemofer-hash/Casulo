from __future__ import annotations

import hashlib

import pytest

from casulo.t.semantic_ir import SemanticIRError, SemanticLowerer, build_semantic_tcap, invalidation_closure
from casulo.t.tcap import parse_tcap


def manifest(name: str, capabilities: tuple[str, ...] = ()) -> dict:
    return {
        "universe_id": name,
        "version": 1,
        "content_hash": hashlib.sha256(name.encode()).hexdigest(),
        "semantic_address": [name, "diagnostico"],
        "invariants": ["intent", "units", "provenance"],
        "capabilities": list(capabilities),
        "neighbors": ["interface" if name == "sinais" else "sinais"],
        "resolution_levels": ["identity", "working"],
        "activation_profile": {"memory_bytes": 4096},
    }


def transition(source: str = "sinais", destination: str = "interface") -> dict:
    return {
        "transition_id": "sinais-interface",
        "source": source,
        "destination": destination,
        "input_contract": "SignalV1",
        "output_contract": "InterfaceV1",
        "projection": {"projection_id": "signal-ui", "required_fields": ["intent", "units", "provenance"], "fallback": "FullSafeProjection"},
        "preserved_invariants": ["intent", "units", "provenance"],
        "required_effects": ["catalog.read", "transition.execute"],
        "budget": {"latency_ms": 30, "memory_bytes": 8192, "transfer_bytes": 4096, "semantic_risk": 0.1, "fidelity": 1.0},
    }


def test_semantic_ir_lowers_to_real_tcap_and_scoped_impact() -> None:
    program = SemanticLowerer().lower((manifest("sinais"), manifest("interface")), (transition(),))
    assert program.effects == ("catalog.read", "transition.execute")
    assert invalidation_closure(program, "sinais") == ("sinais", "sinais-interface")
    package = parse_tcap(build_semantic_tcap(program))
    assert package.manifest["abi"] == "casulo-semantic-ir/1.0"
    assert package.manifest["capability_requirements"] == ["catalog.read", "transition.execute"]
    assert {item.name for item in package.segments} == {"semantic.entry", "semantic.ir.json"}


def test_semantic_ir_rejects_capability_escalation_and_denied_effect() -> None:
    with pytest.raises(SemanticIRError, match="TSM022"):
        SemanticLowerer().lower((manifest("sinais"), manifest("interface", ("secret.read",))), (transition(),))
    bad = transition()
    bad["required_effects"] = ["quantum.qpu.submit"]
    with pytest.raises(SemanticIRError, match="TSM021"):
        SemanticLowerer().lower((manifest("sinais"), manifest("interface")), (bad,))


def test_semantic_ir_rejects_missing_invariant_and_dimensionless_budget() -> None:
    bad = transition()
    bad["preserved_invariants"] = ["intent", "units"]
    with pytest.raises(SemanticIRError, match="TSM023"):
        SemanticLowerer().lower((manifest("sinais"), manifest("interface")), (bad,))
    bad = transition()
    bad["budget"]["latency_ms"] = 1.5
    with pytest.raises(SemanticIRError, match="TSM092"):
        SemanticLowerer().lower((manifest("sinais"), manifest("interface")), (bad,))
