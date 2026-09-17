from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from casulo.t import check_file, check_source
from casulo.t.learn_native import (
    LEARN_NATIVE_ABI,
    LEARN_NATIVE_TARGET,
    LearnNativeError,
    _git_commit,
    build_learn_tcap,
    compare_legacy_oracle,
    lower_learn_native,
    _validate_self_contained_inspection,
)
from casulo.t.learn_canary import parse_flood_canary, verify_canary_oracle
from casulo.t.tcap import TcapError, parse_tcap
from casulo.t.training import build_training_artifact


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "t" / "flood_surrogate_training.t"


def test_compiler_provenance_identifies_the_actual_dirty_source_tree() -> None:
    identity = _git_commit(ROOT)

    assert re.fullmatch(
        r"[0-9a-f]{40}\+dirty-tree-[0-9a-f]{64}", identity
    ), identity


def _toolchain_available() -> bool:
    if shutil.which("rustup") is None:
        return False
    import subprocess

    result = subprocess.run(
        ["rustup", "which", "--toolchain", "nightly-2026-02-01", "rustc"],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode == 0


def test_general_ir_and_graph_are_the_only_native_plan_inputs() -> None:
    checked = check_file(EXAMPLE)
    assert checked.ok and checked.ir is not None and checked.graph is not None
    plan = lower_learn_native(checked.ir, checked.graph)

    assert plan.instruction_ops == plan.graph_node_kinds
    assert plan.resource_contract.max_threads == 1
    assert plan.resource_contract.energy_budget_joules is None
    assert plan.resource_contract.quality_definition["target_loss"] == 0.08
    assert compare_legacy_oracle(plan, EXAMPLE.read_text(encoding="utf-8"))["passed"]
    same_source = EXAMPLE.read_text(encoding="utf-8")
    relocated = check_source(same_source, file="D:/relocated/FloodSurrogate.t")
    assert relocated.ir is not None and relocated.graph is not None
    relocated_plan = lower_learn_native(relocated.ir, relocated.graph)
    assert relocated_plan.ir_sha256 == plan.ir_sha256
    assert relocated_plan.graph_sha256 == plan.graph_sha256


def test_graph_or_instruction_divergence_fails_closed() -> None:
    checked = check_file(EXAMPLE)
    assert checked.ir is not None and checked.graph is not None
    operation = checked.ir.operations[0]
    altered_operation = dataclasses.replace(
        operation,
        instructions=tuple(reversed(operation.instructions)),
    )
    altered_ir = dataclasses.replace(checked.ir, operations=(altered_operation,))

    with pytest.raises(LearnNativeError, match="instruction sequence"):
        lower_learn_native(altered_ir, checked.graph)


@pytest.mark.parametrize(
    ("sections", "undefined", "disassembly", "message"),
    [
        ("  Name: .got\n", "", "", "linkage sections"),
        ("", " U __muldf3\n", "", "undefined symbols"),
        ("", "", "  11f8: ff d3 callq *%rbx\n", "indirect control transfer"),
        (
            "",
            "",
            "  11cb: 48 8b 1d movq -0x11d2(%rip), %rbx # 0x0\n",
            "unmapped low page",
        ),
    ],
)
def test_raw_aot_audit_rejects_linkage_and_low_page_dependencies(
    sections: str, undefined: str, disassembly: str, message: str
) -> None:
    with pytest.raises(LearnNativeError, match=message):
        _validate_self_contained_inspection(
            sections=sections,
            undefined_symbols=undefined,
            disassembly=disassembly,
        )


def test_historical_training_artifact_records_general_lowering(tmp_path: Path) -> None:
    artifact = build_training_artifact(EXAMPLE, tmp_path / "artifact")

    assert artifact.manifest["lowering"]["protocol"] == "casulo-learn-native-plan/0.1"
    assert artifact.manifest["lowering"]["legacy_role"] == "equivalence-comparator-only"
    assert len(artifact.manifest["lowering"]["ir_sha256"]) == 64


@pytest.mark.skipif(
    not _toolchain_available(), reason="pinned Rust toolchain unavailable"
)
def test_real_tcap_is_reproducible_bounded_and_corruption_is_rejected(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "source-a" / "FloodSurrogate.t"
    second_source = tmp_path / "source-b" / "renamed.t"
    first_source.parent.mkdir()
    second_source.parent.mkdir()
    source = EXAMPLE.read_text(encoding="utf-8")
    first_source.write_text(source, encoding="utf-8", newline="\n")
    second_source.write_text(source, encoding="utf-8", newline="\n")
    first = build_learn_tcap(first_source, tmp_path / "first", commit="test-commit")
    second = build_learn_tcap(second_source, tmp_path / "second", commit="test-commit")
    first_bytes = first.tcap_file.read_bytes()
    second_bytes = second.tcap_file.read_bytes()

    assert first_bytes == second_bytes
    assert first.artifact_sha256 == hashlib.sha256(first_bytes).hexdigest()
    package = parse_tcap(first_bytes)
    assert package.manifest["target"] == LEARN_NATIVE_TARGET
    assert package.manifest["abi"] == LEARN_NATIVE_ABI
    assert package.manifest["entry_point"] == {"segment": "code", "offset": 0}
    assert [item.name for item in package.segments] == [
        "code",
        "plan",
        "ir",
        "graph",
        "source",
        "canary",
    ]
    code = package.segments[0].data
    assert code == first.native_binary_file.read_bytes()
    assert not code.startswith(b"\x7fELF")
    assert first.native_elf_file.read_bytes().startswith(b"\x7fELF")

    evidence = json.loads(first.evidence_file.read_text(encoding="utf-8"))
    assert (
        evidence["negative_validation"]["single_byte_segment_corruption"] == "REJECTED"
    )
    assert evidence["claims"]["kernel_execution_proven"] is False
    assert evidence["claims"]["host_canary_oracle_equivalence_proven"] is True
    assert evidence["canary_scope"]["not_a_performance_campaign"] is True
    assert evidence["equivalence"]["quality_gate"] == "BLOCKED_KERNEL_EXECUTION"
    canary = parse_flood_canary(package.segments[-1].data)
    oracle = verify_canary_oracle(canary)
    assert oracle["final_loss"] <= oracle["target_loss"]
    corrupted = bytearray(first_bytes)
    corrupted[-1] ^= 1
    with pytest.raises(TcapError, match="hash mismatch"):
        parse_tcap(bytes(corrupted))
