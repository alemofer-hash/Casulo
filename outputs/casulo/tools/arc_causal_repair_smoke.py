from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from casulo.product.causal_repair import (
    CausalRepairPlanner,
    CausalRepairReceipt,
    bind_intent_requirements,
)
from casulo.product.intent_reconstruction import (
    HypothesisImpactStatus,
    HypothesisRequirementImpact,
    IntentEvidenceKind,
    IntentHypothesis,
    IntentObservation,
    IntentStakes,
    IntentTaskKind,
    IntentTwin,
)
from casulo.product.revolution_contracts import RequirementStrength
from casulo.product.t_forge import ForgeUnit, TForge
from casulo.t.artifact import ArtifactBuilder, EXECUTABLE_FILE
from casulo_owner.generative_forge import GeneratedTProject, compile_generated_project
from casulo_owner.local_model_runtime import StochasticTrace


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _source(module: str, emitted: str) -> str:
    return f'''language T/1.1
module {module}

capability manifest

field Input
  trace value: Text

condense Act in Input
  effects [manifest]
  emit "{emitted}"
'''


def _twin() -> IntentTwin:
    observations = (
        IntentObservation(
            "obs:purpose",
            "Preservar decisões",
            IntentEvidenceKind.EXPLICIT,
            RequirementStrength.HARD,
            ("human:smoke:idea",),
            (("purpose", "summary"),),
            ("verifier:acceptance",),
            1.0,
        ),
        IntentObservation(
            "obs:approval",
            "Exigir confirmação antes da revisão",
            IntentEvidenceKind.EXPLICIT,
            RequirementStrength.HARD,
            ("human:smoke:idea",),
            (("behavior", "approval"),),
            ("verifier:process",),
            1.0,
        ),
    )
    hypothesis = IntentHypothesis(
        "hyp:consultive",
        "Agente consultivo com confirmação",
        "autonomia",
        "confirm-first",
        "execute-first",
        ("Preserva decisão e pede confirmação",),
        1.0,
        tuple(item.observation_id for item in observations),
        tuple(
            HypothesisRequirementImpact(
                item.observation_id,
                HypothesisImpactStatus.PRESERVES,
                "preservado pelo contrato confirm-first",
            )
            for item in observations
        ),
    )
    return IntentTwin(
        "twin:arc6-smoke",
        "creation:arc6-smoke",
        "Agente consultivo",
        IntentTaskKind.CREATION,
        IntentStakes.MATERIAL,
        observations,
        (hypothesis,),
        (),
        selected_hypothesis_id=hypothesis.hypothesis_id,
    ).confirm(
        human_event_id="human:smoke:confirm",
        explicit_human_approval=True,
    )


def _units() -> tuple[ForgeUnit, ...]:
    return (
        ForgeUnit(
            "decision",
            _source("generated.decision", "decisão"),
            (("purpose",),),
        ),
        ForgeUnit(
            "review",
            _source("generated.review", "revisão"),
            (("behavior",),),
            ("decision",),
        ),
        ForgeUnit(
            "output",
            _source("generated.output", "saída"),
            (("interface",),),
            ("review",),
        ),
        ForgeUnit(
            "identity",
            _source("generated.identity", "nome"),
            (("identity",),),
        ),
    )


def _execute_units(units: tuple[ForgeUnit, ...], root: Path) -> list[dict[str, Any]]:
    expected = {
        "decision": "decisão",
        "review": "confirmação",
        "output": "saída",
        "identity": "nome",
    }
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    results: list[dict[str, Any]] = []
    for unit in units:
        unit_root = root / unit.unit_id
        unit_root.mkdir(parents=True)
        source = unit_root / "source.t"
        source.write_text(unit.source, encoding="utf-8", newline="\n")
        artifact = ArtifactBuilder().build(source, unit_root / "artifact")
        operation = str(artifact.manifest["operations"][0]["name"])
        process = subprocess.run(
            [sys.executable, str(artifact.output_dir / EXECUTABLE_FILE), operation, "-"],
            input=json.dumps({"value": "smoke"}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=5,
            env=environment,
            check=False,
        )
        observed = ""
        if process.returncode == 0:
            payload = json.loads(process.stdout)
            observed = str(payload.get("result", ""))
        passed = process.returncode == 0 and expected[unit.unit_id] in observed
        results.append(
            {
                "unit_id": unit.unit_id,
                "operation": operation,
                "expected_contains": expected[unit.unit_id],
                "observed": observed,
                "returncode": process.returncode,
                "passed": passed,
                "stdout_sha256": hashlib.sha256(process.stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(process.stderr.encode()).hexdigest(),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output já existe; evidência append-only recusou overwrite")
    output.mkdir(parents=True)

    twin = _twin()
    before_units = _units()
    bindings = bind_intent_requirements(twin, before_units)
    diagnostic = {
        "schema": "casulo.generative-diagnostic/1.0",
        "code": "TTEST_EXPECTED_TEXT_MISSING",
        "test_name": "approval",
        "unit_id": "review",
        "expected_contains": "confirmação",
        "observed": "revisão",
        "source_sha256": hashlib.sha256(before_units[1].source.encode()).hexdigest(),
    }
    plan = CausalRepairPlanner.plan(
        diagnostic,
        bindings=bindings,
        units=before_units,
        source_event_id="verifier:diagnostic:0:approval",
    )
    forge = TForge()
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
    trace = StochasticTrace(
        "arc6:deterministic-contract-smoke",
        "no-neural-model-used",
        "0" * 64,
        "deterministic-contract-smoke",
        0,
        "1" * 64,
        "2" * 64,
        0,
        "not-applicable",
        now_ns,
        now_ns,
    )
    tests = (
        {"name": "decision", "unit_id": "decision", "input": "smoke", "expected_contains": "decisão"},
        {"name": "approval", "unit_id": "review", "input": "smoke", "expected_contains": "confirmação"},
        {"name": "output", "unit_id": "output", "input": "smoke", "expected_contains": "saída"},
        {"name": "identity", "unit_id": "identity", "input": "smoke", "expected_contains": "nome"},
    )
    before_project = GeneratedTProject(
        "t-project:arc6-smoke-before",
        "3" * 64,
        before_units,
        tests,
        "review",
        trace,
        "4" * 64,
    )
    before_compiled = compile_generated_project(before_project, forge)
    after_units = tuple(
        replace(
            unit,
            source=_source("generated.review", "revisão com confirmação"),
        )
        if unit.unit_id == "review"
        else unit
        for unit in before_units
    )
    after_project = replace(
        before_project,
        project_id="t-project:arc6-smoke-after",
        units=after_units,
        raw_sha256="5" * 64,
    )
    after_compiled = compile_generated_project(
        after_project, forge, affected_paths=plan.affected_paths
    )
    executions = _execute_units(after_units, output / "executions")
    all_passed = all(item["passed"] for item in executions)
    receipt = CausalRepairReceipt.seal(
        plan,
        before_receipt=before_compiled.forge_receipt,
        after_receipt=after_compiled.forge_receipt,
        before_tcap_sha256=before_compiled.tcap_sha256,
        after_tcap_sha256=after_compiled.tcap_sha256,
        changed_unit_ids=("review",),
        all_tests_passed_after_rebuild=all_passed,
    )

    _write_json(output / "intent-twin.json", twin.to_dict())
    _write_json(
        output / "requirement-semantic-bindings.json",
        {
            "schema": "casulo.requirement-semantic-bindings/1.0",
            "bindings": [item.to_dict() for item in bindings],
        },
    )
    _write_json(output / "diagnostic.json", diagnostic)
    _write_json(output / "causal-plan.json", plan.to_dict())
    _write_json(output / "forge-before.json", before_compiled.forge_receipt.to_dict())
    _write_json(output / "forge-after.json", after_compiled.forge_receipt.to_dict())
    _write_json(output / "execution-tests.json", {"tests": executions})
    _write_json(output / "causal-repair-receipt.json", receipt.to_dict())
    gate = {
        "schema": "casulo.arc6-contract-smoke/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "DETERMINISTIC_CONTRACT_SMOKE_NOT_OWNER_NEURAL_PROOF",
        "checks": {
            "confirmed_requirements_bound": len(bindings) == 2,
            "diagnostic_has_requirement": bool(plan.requirement_ids),
            "minimal_rebuild_exact": after_compiled.forge_receipt.rebuilt_units == ("review", "output"),
            "unaffected_artifacts_reused": after_compiled.forge_receipt.reused_units == ("decision", "identity"),
            "tcap_hashes_are_real_and_distinct": (
                before_compiled.tcap_sha256 != after_compiled.tcap_sha256
                and hashlib.sha256(before_compiled.tcap).hexdigest() == before_compiled.tcap_sha256
                and hashlib.sha256(after_compiled.tcap).hexdigest() == after_compiled.tcap_sha256
            ),
            "all_external_t_executions_passed": all_passed,
            "receipt_sealed": len(receipt.receipt_sha256) == 64,
            "neural_owner_proof_claimed": False,
            "scientific_benchmark_started": False,
        },
    }
    gate["status"] = "PASS" if all(
        value is (False if key in {"neural_owner_proof_claimed", "scientific_benchmark_started"} else True)
        for key, value in gate["checks"].items()
    ) else "FAIL"
    _write_json(output / "gate.json", gate)

    files = sorted(
        path for path in output.rglob("*") if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}
    )
    manifest = {
        "schema": "casulo.append-only-manifest/1.0",
        "files": [
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in files
        ],
    }
    _write_json(output / "MANIFEST.json", manifest)
    sums = "".join(
        f"{item['sha256']}  {item['path']}\n" for item in manifest["files"]
    )
    (output / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
    print(json.dumps({"status": gate["status"], "output": str(output), "receipt_sha256": receipt.receipt_sha256}))
    return 0 if gate["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
