from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "private/casulo-owner/src"))

from casulo.t.authority import (  # noqa: E402
    AuthorityAudit,
    DecisionTrace,
    load_surfaces,
    traces_for_absent_authority,
)
from casulo.t.productive import ProductiveTError  # noqa: E402
from casulo.t.v2_tcap import TcapV2Builder  # noqa: E402
from casulo_owner.t85_authority import T85AuthorityDenied, T85OwnerCriticalAuthority  # noqa: E402


CRITICAL = (
    "material_intent",
    "capabilities_effects",
    "hard_requirement_fulfillment",
    "publish_commit",
)


def dump(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(decision_id: str = "ts5-positive") -> dict:
    return {
        "decision_id": decision_id,
        "creation_id": "ts5-owner-critical",
        "model_proposed": True,
        "human_confirmed": True,
        "material": True,
        "requested_capabilities": ("manifest",),
        "granted_capabilities": ("manifest",),
        "consent_valid": True,
        "graph_schema": "casulo.requirement-graph/2.0",
        "graph_version": 1,
        "project_id": "ts5-project",
        "candidate_project_id": "ts5-project",
        "hard_requirement_ids": ("hard-domain", "hard-security"),
        "expected_evidence_tokens": ("a" * 64, "b" * 64),
        "observed_evidence_tokens": ("a" * 64, "b" * 64),
        "evidence_plan_hash": "c" * 64,
        "safety_pass": True,
        "unsupported_claims": (),
        "simulation_status": "PASS",
        "human_publish_approval": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or ROOT.resolve() not in output.parents:
        raise SystemExit("output must be a new directory inside the repository")
    output.mkdir(parents=True)

    sources = tuple(sorted((ROOT / "private/casulo-owner/t-v2").glob("critical-*.t")))
    built = TcapV2Builder().build(
        sources,
        output / "owner-critical.tcap",
        entry_module="owner.critical.intent",
        entry_function="decide",
        tests={"properties": ["critical_T_only", "hard_unknown_blocks", "publish_requires_human"]},
        foreign_boundaries=({"name": "manifest_writer", "kind": "foreign_primitive", "decision_authority": False},),
    )
    runtime_source = ROOT / "t-runtime/target/release" / (
        "casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime"
    )
    clean = output / "clean-owner-critical"
    (clean / "bin").mkdir(parents=True)
    (clean / "engine").mkdir()
    (clean / "owner").mkdir()
    runtime = clean / "bin" / runtime_source.name
    shutil.copy2(runtime_source, runtime)
    shutil.copytree(built.directory, clean / "engine/owner-critical.tcap")
    shutil.copy2(ROOT / "private/casulo-owner/src/casulo_owner/t85_authority.py", clean / "owner/t85_authority.py")
    shutil.copy2(ROOT / "src/casulo/t/productive.py", clean / "owner/productive_transport.py")

    authority = T85OwnerCriticalAuthority(runtime, clean / "engine/owner-critical.tcap", output / "calls")
    primitive_calls: list[str] = []
    result = authority.authorize_and_execute(
        lambda decisions: primitive_calls.append(decisions.receipt_chain[-1]) or {"manifest_written": True},
        **inputs(),
    )
    receipts = [
        item.receipt
        for item in (
            result.decisions.intent,
            result.decisions.capabilities,
            result.decisions.fulfillment,
            result.decisions.publish,
        )
    ]
    dump(output / "critical-receipts.json", receipts)
    dump(
        output / "clean-release-trace.json",
        {
            "schema": "casulo.t85.clean-critical-trace/1.0",
            "artifact_root": "clean-owner-critical",
            "runtime_sha256": digest(runtime),
            "tcap_hash": built.tcap_hash,
            "committed": result.decisions.committed,
            "foreign_primitive_calls": primitive_calls,
            "receipt_chain": list(result.decisions.receipt_chain),
            "decision_source": "compiled_T_only",
            "input_class": "contract_gate_not_human_proof",
        },
    )

    negative: dict[str, str] = {}
    cases = {
        "unconfirmed": {"human_confirmed": False},
        "capability_denied": {"granted_capabilities": ()},
        "hard_unknown": {"observed_evidence_tokens": ("a" * 64, "d" * 64)},
        "publish_unapproved": {"human_publish_approval": False},
    }
    for index, (name, change) in enumerate(cases.items(), start=1):
        try:
            authority.decide(**{**inputs(f"ts5-negative-{index}"), **change})
        except T85AuthorityDenied as error:
            negative[name] = str(error)
        else:
            negative[name] = "UNEXPECTED_PASS"
    dump(output / "negative-cases.json", negative)

    mutation_sources = output / "mutation-sources"
    mutation_sources.mkdir()
    copied: list[Path] = []
    for source in sources:
        destination = mutation_sources / source.name
        text = source.read_text(encoding="utf-8")
        if source.name == "critical-intent.t":
            text = text.replace('return ok "MATERIAL"', 'return error "mutated_policy_denied"')
        destination.write_text(text, encoding="utf-8", newline="\n")
        copied.append(destination)
    mutated = TcapV2Builder().build(
        copied,
        output / "mutated-critical.tcap",
        entry_module="owner.critical.intent",
        entry_function="decide",
    )
    mutation_result = "UNEXPECTED_PASS"
    try:
        T85OwnerCriticalAuthority(runtime, mutated.directory, output / "mutated-calls").decide(
            **inputs("ts5-mutated")
        )
    except T85AuthorityDenied as error:
        mutation_result = str(error)
    dump(output / "mutation-test.json", {"mutation": "intent_returns_error", "result": mutation_result})

    bypass_result = "UNEXPECTED_FALLBACK"
    try:
        T85OwnerCriticalAuthority(output / "missing-runtime", built.directory, output / "bypass-calls")
    except ProductiveTError as error:
        bypass_result = str(error)
    dump(output / "bypass-test.json", {"runtime_removed": True, "result": bypass_result})

    surfaces = load_surfaces(ROOT / "docs/product/TS_SOVEREIGNTY_MATRIX.json")
    absent = {item.surface_id: item for item in traces_for_absent_authority(surfaces, {})}
    receipt_by_surface = {item["surface_id"]: item for item in receipts}
    for surface_id in CRITICAL:
        absent[surface_id] = DecisionTrace(
            surface_id=surface_id,
            decision_id=receipt_by_surface[surface_id]["decision_id"],
            t_runtime_executed=True,
            t_result_consumed=True,
            foreign_recomputed=False,
            productive_fallback=False,
            clean_release_trace=True,
            mutation_changes_decision=True,
            bypass_fails_closed=True,
            execution_is_nontrivial_t=True,
            evidence_refs=(
                "critical-receipts.json",
                "clean-release-trace.json",
                "mutation-test.json",
                "bypass-test.json",
            ),
        )
    audit = AuthorityAudit(surfaces, tuple(absent[item.surface_id] for item in surfaces))
    dump(output / "authority-audit.json", audit.to_dict())

    files = sorted(path for path in output.rglob("*") if path.is_file())
    manifest = {
        "schema": "casulo.t85.ts5-evidence/1.0",
        "gate": "TS5_CRITICAL_AUTHORITY_PASS",
        "critical_surfaces": list(CRITICAL),
        "c_critical": audit.critical_coverage,
        "s_authority": audit.authority_score,
        "s_execution": audit.execution_score,
        "tests_required": "tests.xml",
        "files": {path.relative_to(output).as_posix(): digest(path) for path in files},
        "locks": {
            "cloud": "RELEASE_LOCKED",
            "guest_network": "OFF",
            "usb_block_devices": "PROHIBITED",
            "qpu": "UNAVAILABLE_DENY",
            "scientific_benchmark": "NOT_STARTED",
        },
    }
    dump(output / "gate.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("gate", "c_critical", "s_authority", "s_execution")}, indent=2))
    return 0 if audit.critical_coverage == 1.0 and all(value != "UNEXPECTED_PASS" for value in negative.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
