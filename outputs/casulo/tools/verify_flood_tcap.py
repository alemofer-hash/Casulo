"""Independently verify the FloodSurrogate TCAP and fail-closed probes."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.t.api import check_source  # noqa: E402
from casulo.t.learn_native import (  # noqa: E402
    LEARN_NATIVE_ABI,
    LEARN_NATIVE_TARGET,
    compare_legacy_oracle,
    lower_learn_native,
    portable_ir_document,
)
from casulo.t.learn_canary import (  # noqa: E402
    CANARY_PROTOCOL,
    parse_flood_canary,
    verify_canary_oracle,
)
from casulo.t.tcap import TcapError, canonical_json, parse_tcap  # noqa: E402


def verify(artifact_path: Path, evidence_path: Path) -> dict[str, object]:
    raw = artifact_path.read_bytes()
    package = parse_tcap(raw)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    segments = {item.name: item.data for item in package.segments}
    if set(segments) != {"code", "plan", "ir", "graph", "source", "canary"}:
        raise AssertionError("unexpected TCAP segment set")
    if package.manifest["target"] != LEARN_NATIVE_TARGET:
        raise AssertionError("unexpected target")
    if package.manifest["abi"] != LEARN_NATIVE_ABI:
        raise AssertionError("unexpected ABI")
    if package.manifest["entry_point"] != {"segment": "code", "offset": 0}:
        raise AssertionError("unexpected entry point")

    source = segments["source"].decode("utf-8")
    checked = check_source(source, file="FloodSurrogate.tcap:source")
    if not checked.ok or checked.ir is None or checked.graph is None:
        raise AssertionError("embedded source no longer passes the general pipeline")
    plan = lower_learn_native(checked.ir, checked.graph)
    if canonical_json(plan.to_dict()) != segments["plan"]:
        raise AssertionError("embedded plan differs from fresh general lowering")
    if canonical_json(portable_ir_document(checked.ir)) != segments["ir"]:
        raise AssertionError("embedded IR differs from source")
    if canonical_json(checked.graph.to_dict()) != segments["graph"]:
        raise AssertionError("embedded graph differs from IR")
    oracle = compare_legacy_oracle(plan, source)
    if not oracle["passed"]:
        raise AssertionError("legacy equivalence oracle differs")
    canary = parse_flood_canary(segments["canary"])
    canary_result = verify_canary_oracle(canary)
    if canary_result["protocol"] != CANARY_PROTOCOL:
        raise AssertionError("unexpected numerical canary protocol")
    if canary.epochs != plan.epochs or canary.learning_rate != plan.learning_rate:
        raise AssertionError("canary execution contract differs from native plan")
    if canary.target_loss != plan.target_loss:
        raise AssertionError("canary quality target differs from native plan")
    canary_sha256 = hashlib.sha256(segments["canary"]).hexdigest()
    canary_evidence = evidence.get("canary_scope", {})
    if canary_evidence.get("segment_sha256") != canary_sha256:
        raise AssertionError("canary hash differs from evidence")
    if canary_evidence.get("not_a_performance_campaign") is not True:
        raise AssertionError("canary scope is not explicitly correctness-only")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != evidence["artifact"]["sha256"]:
        raise AssertionError("artifact hash differs from evidence")
    toolchain = evidence.get("compiler", {}).get("underlying_toolchain", {})
    static_audit = toolchain.get("position_independent_audit", {})
    runtime_audit = toolchain.get("runtime_position_independent_audit", {})
    if static_audit.get("status") != "PASS":
        raise AssertionError("self-contained raw AOT static audit is absent")
    if runtime_audit.get("status") != "PASS":
        raise AssertionError("dynamic-address raw AOT runtime audit is absent")
    if toolchain.get("float_execution") != "sse2-hard-float-memory-context":
        raise AssertionError("unexpected native float execution contract")

    corrupted = bytearray(raw)
    corrupted[-1] ^= 1
    corruption_rejected = False
    try:
        parse_tcap(bytes(corrupted))
    except TcapError:
        corruption_rejected = True
    if not corruption_rejected:
        raise AssertionError("single-byte corruption was accepted")

    operation = checked.ir.operations[0]
    altered = dataclasses.replace(
        checked.ir,
        operations=(
            dataclasses.replace(
                operation,
                instructions=tuple(reversed(operation.instructions)),
            ),
        ),
    )
    semantic_mismatch_rejected = False
    try:
        lower_learn_native(altered, checked.graph)
    except RuntimeError:
        semantic_mismatch_rejected = True
    if not semantic_mismatch_rejected:
        raise AssertionError("IR/graph semantic mismatch was accepted")

    return {
        "protocol": "casulo-flood-tcap-independent-verification/0.1",
        "artifact": str(artifact_path.resolve()),
        "sha256": digest,
        "checks": {
            "canonical_integrity": "PASS",
            "target_abi_entry": "PASS",
            "source_ir_graph_plan_trace": "PASS",
            "legacy_oracle_comparator": "PASS",
            "numerical_canary_independent_oracle": "PASS",
            "numerical_canary_quality_target": "PASS",
            "raw_aot_self_contained_static_audit": "PASS",
            "raw_aot_dynamic_address_runtime_audit": "PASS",
            "single_byte_corruption": "REJECTED",
            "ir_graph_semantic_mismatch": "REJECTED",
        },
        "claims": {
            "kernel_execution_proven": False,
            "kernel_numerical_equivalence_proven": False,
            "performance_measured": False,
        },
        "canary": {
            **canary_result,
            "role": "bounded-correctness-canary",
            "not_a_performance_campaign": True,
            "segment_sha256": canary_sha256,
            "segment_bytes": len(segments["canary"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact", type=Path, default=ROOT / "release" / "FloodSurrogate.tcap"
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "release" / "FloodSurrogate.evidence.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.artifact, args.evidence)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        destination = args.output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
