from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from casulo.t.stdlib import ProductiveTStandardLibrary, STAGES
from casulo.t.v2_tcap import TcapV2Builder, verify_tcap_v2


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")


def build(tmp_path: Path, sources: tuple[Path, ...] | None = None) -> Path:
    selected = sources or tuple(sorted((ROOT / "stdlib/t-v2").glob("*.t")))
    boundaries = json.loads((ROOT / "docs/product/TS_FOREIGN_BOUNDARIES.json").read_text(encoding="utf-8"))["boundaries"]
    return TcapV2Builder().build(
        selected, tmp_path / "stdlib.tcap", entry_module="t.core.result", entry_function="decide",
        foreign_boundaries=boundaries,
    ).directory


def test_productive_vertical_traverses_all_modules_and_chains_receipts(tmp_path: Path) -> None:
    tcap = build(tmp_path)
    result = ProductiveTStandardLibrary(RUNTIME).run(tcap, tmp_path / "run")
    assert result.status == "PASS"
    assert result.final_value == "SEALED"
    assert [item["module"] for item in result.stages] == [stage.module for stage in STAGES]
    assert len(result.stages) == 13
    previous = "0" * 64
    for item in result.stages:
        assert item["receipt"]["previous_receipt_hash"] == previous
        previous = item["receipt"]["receipt_hash"]
    assert [effect for item in result.stages for effect in item["observable"]["requested_effects"]] == ["simulation", "manifest"]


def test_hard_unknown_blocks_before_capability_or_publish(tmp_path: Path) -> None:
    stages = tuple(
        replace(stage, fixed_input={**stage.fixed_input, "hard_statuses": ["UNKNOWN"]})
        if stage.module == "t.casulo.requirements" else stage
        for stage in STAGES
    )
    result = ProductiveTStandardLibrary(RUNTIME).run(build(tmp_path), tmp_path / "run", stages=stages)
    assert result.status == "BLOCKED"
    assert result.stages[-1]["module"] == "t.casulo.requirements"
    assert result.stages[-1]["observable"]["result"] == {"kind": "error", "value": "hard_requirement_not_pass"}
    assert all(item["module"] != "t.casulo.materialization" for item in result.stages)


def test_project_bleed_is_denied_by_t_memory_policy(tmp_path: Path) -> None:
    stages = tuple(
        replace(stage, fixed_input={**stage.fixed_input, "project_id": "project:other"})
        if stage.module == "t.casulo.memory_policy" else stage
        for stage in STAGES
    )
    result = ProductiveTStandardLibrary(RUNTIME).run(build(tmp_path), tmp_path / "run", stages=stages)
    assert result.status == "BLOCKED"
    assert result.stages[-1]["observable"]["result"]["value"] == "project_bleed_denied"


def test_mutating_t_intent_changes_and_blocks_downstream_decision(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    copied: list[Path] = []
    for source in sorted((ROOT / "stdlib/t-v2").glob("*.t")):
        content = source.read_text(encoding="utf-8")
        if source.name == "casulo-intent.t":
            content = content.replace('return ok "MATERIAL"', 'return ok "INFORMAL"')
        target = source_dir / source.name
        target.write_text(content, encoding="utf-8", newline="\n")
        copied.append(target)
    result = ProductiveTStandardLibrary(RUNTIME).run(build(tmp_path, tuple(copied)), tmp_path / "run")
    assert result.status == "BLOCKED"
    assert result.stages[-2]["observable"]["result"]["value"] == "INFORMAL"
    assert result.stages[-1]["observable"]["result"]["value"] == "intent_chain_broken"


def test_bypassing_a_t_stage_fails_closed(tmp_path: Path) -> None:
    stages = tuple(stage for stage in STAGES if stage.module != "t.casulo.intent")
    result = ProductiveTStandardLibrary(RUNTIME).run(build(tmp_path), tmp_path / "run", stages=stages)
    assert result.status == "BLOCKED"
    assert result.stages[-1]["module"] == "t.casulo.requirements"
    assert result.stages[-1]["observable"]["result"]["value"] == "intent_chain_broken"


def test_stdlib_tcap_is_source_ir_consistent_and_not_decorative(tmp_path: Path) -> None:
    root, manifest, typed = verify_tcap_v2(build(tmp_path))
    assert len(manifest["sources"]) == len(typed["modules"]) == 13
    assert {item["module"] for item in typed["modules"]} == {stage.module for stage in STAGES}
    for module in typed["modules"]:
        code = module["functions"][0]["code"]
        assert code
        assert code != [{"op": "ret"}]
    source_text = "\n".join((root / item["file"]).read_text(encoding="utf-8") for item in manifest["sources"])
    assert "emit_literal" not in source_text
