from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.t.api import check_file, check_source
from casulo.t.expression_ast import BinaryNode, ConditionalNode, parse_expression
from casulo.t.workspace import WorkspaceError, build_workspace, check_workspace


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "examples/t/product_memory.t"


def test_expression_ast_is_owned_and_precedence_is_explicit() -> None:
    root = parse_expression("1 + 2 * 3 if ready else 0")
    assert isinstance(root, ConditionalNode)
    assert isinstance(root.when_true, BinaryNode)
    assert root.when_true.operator == "+"
    assert isinstance(root.when_true.right, BinaryNode)
    assert root.when_true.right.operator == "*"


def test_records_enums_result_cfg_and_capability_lower_together() -> None:
    result = check_file(SOURCE)
    assert result.ok, [item.render() for item in result.diagnostics]
    assert result.ir is not None and result.graph is not None
    assert [item.name for item in result.ir.records] == ["MemoryQuery", "RecallReply"]
    assert result.ir.records[1].traces[0].type_name == "Result[Text,RecallError]"
    assert result.ir.enums[0].cases == ("NotFound", "Ambiguous")
    cfg = result.ir.operations[0].cfg
    assert cfg is not None
    assert len(cfg.blocks) == 4
    assert len(next(block for block in cfg.blocks if block.id == "block/root.0").successors) == 2
    assert result.graph.types[0].kind == "record"
    assert result.graph.operations[0].cfg_entry == "block/root.0"
    assert result.ir.render_text() == (
        ROOT / "conformance/vnext/product_memory.ir"
    ).read_text(encoding="utf-8")
    assert result.graph.render_text() == (
        ROOT / "conformance/vnext/product_memory.graph"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("record X\n  trace value: Text\n", "T3110"),
        ("language T/1.1\nenum X\n  case A\n  case A\n", "T3112"),
        (
            "language T/1.1\nrecord X\n  trace value: Result[Text]\n",
            "T3113",
        ),
    ],
)
def test_product_type_failures_are_diagnostic(source: str, code: str) -> None:
    result = check_source(source, "invalid-product-type.t")
    assert not result.ok
    assert code in {item.code for item in result.diagnostics}


def test_workspace_links_imported_record_and_hashes_interface(tmp_path: Path) -> None:
    root = tmp_path / "linked"
    source_dir = root / "src"
    source_dir.mkdir(parents=True)
    (root / "casulo.toml").write_text(
        "[project]\nname = \"linked\"\nversion = \"0.1.0\"\n"
        "kind = \"application\"\nentry = \"demo.main\"\nsource = \"src\"\n"
        "external_modules = []\n\n[dependencies]\n",
        encoding="utf-8",
    )
    (source_dir / "types.t").write_text(
        "language T/1.1\nmodule demo.types\n\n"
        "record Query\n  trace text: Text\n",
        encoding="utf-8",
    )
    (source_dir / "main.t").write_text(
        "language T/1.1\nmodule demo.main\nuse demo.types\n"
        "capability manifest\n\ncondense Main in Query\n"
        "  effects [manifest]\n  emit text\n",
        encoding="utf-8",
    )
    workspace = check_workspace(root)
    built = build_workspace(root)
    assert workspace.build_order == ("demo.types", "demo.main")
    interface = next(item for item in workspace.interfaces if item.module == "demo.types")
    assert interface.exported_types == ("Query",)
    assert len(interface.sha256) == 64
    document = json.loads((built.output_dir / "workspace.json").read_text("utf-8"))
    assert document["interfaces"][1]["module"] == "demo.types"


def test_workspace_rejects_ambiguous_imported_type(tmp_path: Path) -> None:
    root = tmp_path / "ambiguous"
    source_dir = root / "src"
    source_dir.mkdir(parents=True)
    (root / "casulo.toml").write_text(
        "[project]\nname = \"ambiguous\"\nversion = \"0.1.0\"\n"
        "kind = \"application\"\nentry = \"demo.main\"\nsource = \"src\"\n"
        "external_modules = []\n\n[dependencies]\n",
        encoding="utf-8",
    )
    for module in ("a", "b"):
        (source_dir / f"{module}.t").write_text(
            f"language T/1.1\nmodule demo.{module}\n\n"
            "record Query\n  trace text: Text\n",
            encoding="utf-8",
        )
    (source_dir / "main.t").write_text(
        "language T/1.1\nmodule demo.main\nuse demo.a\nuse demo.b\n"
        "capability manifest\n\ncondense Main in Query\n"
        "  effects [manifest]\n  emit text\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkspaceError, match="T3103"):
        check_workspace(root)
