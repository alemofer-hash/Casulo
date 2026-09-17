from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from casulo.product.domain import canonical_sha256
from casulo.product.causal_repair import (
    CausalRepairPlan,
    CausalRepairPlanner,
    CausalRepairReceipt,
    RequirementSemanticBinding,
)
from casulo.product.engine_contracts import CancellationToken
from casulo.product.platform_contracts import PlatformError
from casulo.product.t_forge import TForge
from casulo.t.artifact import ArtifactBuilder, EXECUTABLE_FILE

from .generative_forge import (
    CandidateBudgetExhausted,
    CompiledTProject,
    GeneratedTProject,
    TProgramSynthesizer,
    compile_generated_project,
    verify_correction_scope,
)


class VerifierRepairError(PlatformError):
    pass


@dataclass(frozen=True, slots=True)
class StructuredDiagnostic:
    code: str
    test_name: str
    unit_id: str
    expected_contains: str
    observed: str
    process_returncode: int
    process_stderr: str
    artifact_id: str
    source_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.generative-diagnostic/1.0",
            "code": self.code,
            "test_name": self.test_name,
            "unit_id": self.unit_id,
            "expected_contains": self.expected_contains,
            "observed": self.observed,
            "process_returncode": self.process_returncode,
            "process_stderr": self.process_stderr,
            "artifact_id": self.artifact_id,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class ExecutedTest:
    name: str
    unit_id: str
    operation: str
    expected_contains: str
    observed: str
    passed: bool
    returncode: int
    wall_ns: int
    stdout_sha256: str
    stderr_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit_id": self.unit_id,
            "operation": self.operation,
            "expected_contains": self.expected_contains,
            "observed": self.observed,
            "passed": self.passed,
            "returncode": self.returncode,
            "wall_ns": self.wall_ns,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
        }


@dataclass(frozen=True, slots=True)
class VerificationAttempt:
    attempt: int
    project_id: str
    tcap_sha256: str
    tests: tuple[ExecutedTest, ...]
    diagnostics: tuple[StructuredDiagnostic, ...]
    started_ns: int
    finished_ns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "project_id": self.project_id,
            "tcap_sha256": self.tcap_sha256,
            "tests": [item.to_dict() for item in self.tests],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "started_ns": self.started_ns,
            "finished_ns": self.finished_ns,
        }


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    status: str
    project: GeneratedTProject
    compiled: CompiledTProject
    attempts: tuple[VerificationAttempt, ...]
    repair_count: int
    budget: int
    causal_repairs: tuple[CausalRepairReceipt, ...]
    receipt_sha256: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.verifier-repair-receipt/1.0",
            "status": self.status,
            "project_id": self.project.project_id,
            "tcap_sha256": self.compiled.tcap_sha256,
            "repair_count": self.repair_count,
            "budget": self.budget,
            "candidate_rejections": list(self.project.candidate_rejections),
            "attempts": [item.to_dict() for item in self.attempts],
            "causal_repairs": [item.to_dict() for item in self.causal_repairs],
            "receipt_sha256": self.receipt_sha256,
        }


class VerifierRepairLoop:
    """Compiles and executes generated T; only real diagnostics may trigger repair."""

    def __init__(
        self,
        synthesizer: TProgramSynthesizer,
        *,
        repair_budget: int = 2,
        process_timeout_seconds: float = 5.0,
    ) -> None:
        if not 0 <= repair_budget <= 4:
            raise VerifierRepairError("repair budget precisa ficar entre zero e quatro")
        if not 0.1 <= process_timeout_seconds <= 30:
            raise VerifierRepairError("timeout do verificador fora do limite")
        self.synthesizer = synthesizer
        self.repair_budget = repair_budget
        self.process_timeout_seconds = process_timeout_seconds

    def run(
        self,
        project: GeneratedTProject,
        *,
        work_root: str | Path,
        cancellation: CancellationToken,
        requirement_bindings: tuple[RequirementSemanticBinding, ...] = (),
        require_causal_repairs: bool = False,
    ) -> RepairOutcome:
        root = Path(work_root).expanduser().resolve()
        if root.exists() or root.is_symlink():
            raise VerifierRepairError("work_root do reparo ja existe; overwrite negado")
        root.mkdir(parents=True)
        forge = TForge()
        current = project
        attempts: list[VerificationAttempt] = []
        compiled: CompiledTProject | None = None
        repair_count = 0
        causal_repairs: list[CausalRepairReceipt] = []
        pending_causal: tuple[
            CausalRepairPlan, CompiledTProject, tuple[str, ...]
        ] | None = None
        for attempt_index in range(self.repair_budget + 1):
            if cancellation.cancelled:
                raise VerifierRepairError("reparo cancelado antes da verificacao")
            compiled = compile_generated_project(
                current,
                forge,
                affected_paths=(
                    pending_causal[0].affected_paths if pending_causal is not None else ()
                ),
            )
            attempt = self._verify(current, compiled, root / f"attempt-{attempt_index}", attempt_index)
            attempts.append(attempt)
            if pending_causal is not None:
                plan, before_compiled, changed_unit_ids = pending_causal
                causal_repairs.append(
                    CausalRepairReceipt.seal(
                        plan,
                        before_receipt=before_compiled.forge_receipt,
                        after_receipt=compiled.forge_receipt,
                        before_tcap_sha256=before_compiled.tcap_sha256,
                        after_tcap_sha256=compiled.tcap_sha256,
                        changed_unit_ids=changed_unit_ids,
                        all_tests_passed_after_rebuild=all(
                            test.passed for test in attempt.tests
                        ),
                    )
                )
                pending_causal = None
            if not attempt.diagnostics:
                return self._outcome(
                    "PASS", current, compiled, attempts, repair_count, causal_repairs
                )
            if attempt_index == self.repair_budget:
                return self._outcome(
                    "REPAIR_BUDGET_EXHAUSTED",
                    current,
                    compiled,
                    attempts,
                    repair_count,
                    causal_repairs,
                )
            diagnostic = attempt.diagnostics[0]
            unit = next(item for item in current.units if item.unit_id == diagnostic.unit_id)
            source_event_id = (
                f"verifier:diagnostic:{attempt_index}:{diagnostic.test_name}"
            )
            causal_plan = (
                CausalRepairPlanner.plan(
                    diagnostic.to_dict(),
                    bindings=requirement_bindings,
                    units=current.units,
                    source_event_id=source_event_id,
                )
                if requirement_bindings
                else None
            )
            if require_causal_repairs and causal_plan is None:
                raise VerifierRepairError(
                    "reparo owner negado: diagnóstico sem binding causal de requisito"
                )
            declared_affected_paths = (
                causal_plan.affected_paths if causal_plan is not None else unit.watch_paths
            )
            unit_diagnostics = [
                item.to_dict() for item in attempt.diagnostics if item.unit_id == unit.unit_id
            ]
            unit_invariants = [
                {
                    "test_name": test["name"],
                    "expected_contains": test["expected_contains"],
                }
                for test in current.tests
                if test["unit_id"] == unit.unit_id
            ]
            try:
                before_project = current
                revised_project = self.synthesizer.revise_unit(
                    before_project,
                    unit_id=unit.unit_id,
                    correction=json.dumps(
                        {
                            "failing_diagnostics": unit_diagnostics,
                            "must_preserve_all_test_expectations": unit_invariants,
                            "instruction": (
                                "emit_literal deve conter simultaneamente todos os expected_contains "
                                "sem remover comportamento que ja passou"
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    declared_affected_paths=declared_affected_paths,
                    source_event_id=source_event_id,
                    cancellation=cancellation,
                )
            except CandidateBudgetExhausted as error:
                current = replace(
                    current,
                    candidate_rejections=(
                        *current.candidate_rejections,
                        *error.rejections,
                    ),
                )
                return self._outcome(
                    "REPAIR_CANDIDATE_BUDGET_EXHAUSTED",
                    current,
                    compiled,
                    attempts,
                    repair_count,
                    causal_repairs,
                )
            changed_unit_ids = verify_correction_scope(
                before_project,
                revised_project,
                declared_affected_paths=declared_affected_paths,
            )
            current = revised_project
            if causal_plan is not None:
                pending_causal = (causal_plan, compiled, changed_unit_ids)
            repair_count += 1
        raise AssertionError("loop de reparo saiu do dominio finito")

    def _verify(
        self,
        project: GeneratedTProject,
        compiled: CompiledTProject,
        attempt_root: Path,
        attempt_index: int,
    ) -> VerificationAttempt:
        started = time.monotonic_ns()
        attempt_root.mkdir()
        built: dict[str, tuple[Path, dict[str, Any], str]] = {}
        for unit in project.units:
            unit_root = attempt_root / unit.unit_id
            unit_root.mkdir()
            source = unit_root / "source.t"
            source.write_text(unit.source, encoding="utf-8", newline="\n")
            result = ArtifactBuilder().build(source, unit_root / "artifact")
            operations = result.manifest.get("operations", [])
            if not isinstance(operations, list) or len(operations) != 1:
                raise VerifierRepairError("unidade T generativa precisa de uma operacao")
            built[unit.unit_id] = (result.output_dir, result.manifest, str(operations[0]["name"]))

        tests: list[ExecutedTest] = []
        diagnostics: list[StructuredDiagnostic] = []
        environment = dict(os.environ)
        environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        by_unit = {unit.unit_id: unit for unit in project.units}
        for test in project.tests:
            unit_id = test["unit_id"]
            if unit_id not in built or unit_id not in by_unit:
                raise VerifierRepairError("teste referencia unidade nao compilada")
            artifact_dir, manifest, operation = built[unit_id]
            command = [sys.executable, str(artifact_dir / EXECUTABLE_FILE), operation, "-"]
            begin = time.perf_counter_ns()
            try:
                process = subprocess.run(
                    command,
                    input=json.dumps({"value": test["input"]}, ensure_ascii=False),
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    timeout=self.process_timeout_seconds,
                    env=environment,
                    check=False,
                )
                stdout, stderr, returncode = process.stdout, process.stderr, process.returncode
            except subprocess.TimeoutExpired as error:
                stdout = error.stdout.decode("utf-8", "replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
                stderr = error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
                returncode = 124
            wall_ns = time.perf_counter_ns() - begin
            observed = ""
            if returncode == 0:
                try:
                    payload = json.loads(stdout)
                    observed = str(payload.get("result", "")) if isinstance(payload, dict) else ""
                except json.JSONDecodeError:
                    returncode = 65
            passed = returncode == 0 and test["expected_contains"].casefold() in observed.casefold()
            executed = ExecutedTest(
                test["name"], unit_id, operation, test["expected_contains"], observed,
                passed, returncode, wall_ns,
                hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
                hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
            )
            tests.append(executed)
            if not passed:
                unit = by_unit[unit_id]
                diagnostics.append(
                    StructuredDiagnostic(
                        "TTEST_EXPECTED_TEXT_MISSING" if returncode == 0 else "TTEST_PROCESS_FAILED",
                        test["name"], unit_id, test["expected_contains"], observed,
                        returncode, stderr[-2048:], str(manifest["artifact_id"]),
                        hashlib.sha256(unit.source.encode("utf-8")).hexdigest(),
                    )
                )
        return VerificationAttempt(
            attempt_index,
            project.project_id,
            compiled.tcap_sha256,
            tuple(tests),
            tuple(diagnostics),
            started,
            time.monotonic_ns(),
        )

    def _outcome(
        self,
        status: str,
        project: GeneratedTProject,
        compiled: CompiledTProject,
        attempts: list[VerificationAttempt],
        repair_count: int,
        causal_repairs: list[CausalRepairReceipt],
    ) -> RepairOutcome:
        unsigned = {
            "schema": "casulo.verifier-repair-receipt/1.0",
            "status": status,
            "project_id": project.project_id,
            "tcap_sha256": compiled.tcap_sha256,
            "repair_count": repair_count,
            "budget": self.repair_budget,
            "candidate_rejections": list(project.candidate_rejections),
            "attempts": [item.to_dict() for item in attempts],
            "causal_repairs": [item.to_dict() for item in causal_repairs],
        }
        return RepairOutcome(
            status, project, compiled, tuple(attempts), repair_count,
            self.repair_budget, tuple(causal_repairs), canonical_sha256(unsigned)
        )
