from __future__ import annotations

from pathlib import Path

import pytest

from casulo.t import check_file, check_source
from casulo.t.artifact import ArtifactBuilder, verify_artifact
from casulo.t.resource import ResourceContract, SemanticClass
from casulo.t.tcap import TcapError, TcapSegment, build_tcap, parse_tcap


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "examples/t/product_capability.t"


def resource_contract() -> ResourceContract:
    return ResourceContract(
        memory_limit_bytes=1 << 20,
        arena_bytes=1 << 18,
        max_threads=1,
        semantic_class=SemanticClass.PRESENCE if hasattr(SemanticClass, "PRESENCE") else SemanticClass.FLOW,
        deterministic=True,
        numerical_precision="integer",
        permissions=("memory", "console"),
        quality_definition={"protocol": "casulo-product-correctness/1"},
        residual_routing={"invalid": "QUARANTINE"},
    )


def test_vnext_capability_traverses_ast_analysis_ir_and_graph() -> None:
    result = check_file(SOURCE)
    assert result.ok, result.diagnostics
    assert result.program.language.version == "T/1.1"
    assert [item.name for item in result.program.capabilities] == ["manifest"]
    operation = result.program.declarations[1]
    assert operation.effects == ("manifest",)
    assert result.analysis.operation_effects["Present"] == ("manifest",)
    assert result.ir.version == "crisalida-ir/1.0"
    assert result.ir.capabilities == ("manifest",)
    assert result.graph.version == "metamorfose-graph/1.0"
    assert result.graph.capabilities == ("manifest",)
    assert result.graph.operations[0].permissions == ("manifest",)


def test_vnext_ir_and_graph_match_goldens() -> None:
    result = check_file(SOURCE)
    assert result.ir.render_text() == (ROOT / "conformance/vnext/product_capability.ir").read_text(encoding="utf-8")
    assert result.graph.render_text() == (ROOT / "conformance/vnext/product_capability.graph").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("language T/1.1\ncapability manifest\ncondense X\n  emit true\n", "T3100"),
        ("language T/1.1\ncondense X\n  effects [manifest]\n  emit true\n", "T3104"),
        ("language T/1.1\ncapability model.unknown\ncondense X\n  effects [manifest]\n  emit true\n", "T3101"),
        ("capability manifest\ncondense X\n  effects [manifest]\n  emit true\n", "T3104"),
    ],
)
def test_vnext_effect_failures_are_diagnostic(source: str, code: str) -> None:
    result = check_source(source, "invalid-vnext.t")
    assert not result.ok
    assert code in [item.code for item in result.diagnostics]
    assert result.ir is None and result.graph is None


def test_vnext_artifact_manifest_preserves_requirements(tmp_path: Path) -> None:
    built = ArtifactBuilder().build(SOURCE, tmp_path / "artifact")
    assert built.manifest["language"] == "T/1.1"
    assert built.manifest["capability_requirements"] == ["manifest"]
    assert built.manifest["operations"][0]["capability_effects"] == ["manifest"]
    _, verified = verify_artifact(built.output_dir)
    assert verified == built.manifest


def test_tcap_11_carries_requirements_but_never_grants() -> None:
    raw = build_tcap(
        segments=(TcapSegment("code", b"\x90\xc3", "rx"),),
        target="x86_64-casulo-none",
        abi="casulo-syscall/0.1",
        entry_segment="code",
        entry_offset=0,
        compiler={"name": "casulo-t", "version": "0.1", "commit": "test"},
        resource_contract=resource_contract(),
        capability_requirements=("manifest",),
    )
    package = parse_tcap(raw)
    assert package.manifest["schema"] == "tcap-manifest/1.1"
    assert package.manifest["capability_requirements"] == ["manifest"]
    assert "grants" not in package.manifest


def test_tcap_11_rejects_unknown_or_duplicate_requirements() -> None:
    common = dict(
        segments=(TcapSegment("code", b"x", "rx"),),
        target="x86_64-casulo-none",
        abi="casulo-syscall/0.1",
        entry_segment="code",
        entry_offset=0,
        compiler={"name": "casulo-t", "version": "0.1", "commit": "test"},
        resource_contract=resource_contract(),
    )
    with pytest.raises(TcapError, match="unknown"):
        build_tcap(capability_requirements=("owner.private",), **common)
    with pytest.raises(TcapError, match="unique"):
        build_tcap(capability_requirements=("manifest", "manifest"), **common)
