from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from casulo.product.domain import (
    CreationAggregate,
    CreationSpec,
    DeltaConfirmation,
    IntentDelta,
    IntentOperation,
    canonical_sha256,
)
from casulo.product.engine_contracts import CancellationToken
from casulo.product.platform_contracts import PlatformError
from casulo.product.t_forge import ForgeArtifact, ForgeReceipt, ForgeUnit, TForge
from casulo.t.api import check_source
from casulo.t.resource import ResourceContract, SemanticClass
from casulo.t.tcap import TcapSegment, build_tcap, parse_tcap

from .local_model_runtime import (
    ChatMessage,
    GenerationRequest,
    LocalModelRuntime,
    ModelStreamKind,
    SamplingPolicy,
    StochasticTrace,
    initial_sampling_policies,
)


class GenerativeForgeError(PlatformError):
    pass


class StructuredGenerationError(GenerativeForgeError):
    """Saída neural concluída, mas estruturalmente recusada antes de virar produto."""

    def __init__(self, message: str, *, trace: StochasticTrace, raw_sha256: str) -> None:
        super().__init__(message)
        self.trace = trace
        self.raw_sha256 = raw_sha256


class CandidateBudgetExhausted(GenerativeForgeError):
    def __init__(self, phase: str, budget: int, rejections: tuple[dict[str, Any], ...]) -> None:
        super().__init__(f"candidatos de {phase} T esgotados ({len(rejections)}/{budget})")
        self.phase = phase
        self.budget = budget
        self.rejections = rejections


@dataclass(frozen=True, slots=True)
class StructuredGeneration:
    payload: dict[str, Any]
    trace: StochasticTrace
    raw_sha256: str


def generate_structured(
    runtime: LocalModelRuntime,
    *,
    operation_id: str,
    messages: tuple[ChatMessage, ...],
    policy: SamplingPolicy,
    schema: dict[str, Any],
    cancellation: CancellationToken,
) -> StructuredGeneration:
    fragments: list[str] = []
    trace: StochasticTrace | None = None
    terminal: ModelStreamKind | None = None
    for event in runtime.stream_chat(
        GenerationRequest(operation_id, messages, policy, json_schema=schema),
        cancellation,
    ):
        if event.kind is ModelStreamKind.TOKEN:
            fragments.append(event.content)
        if event.kind in {ModelStreamKind.COMPLETED, ModelStreamKind.CANCELLED, ModelStreamKind.FAILED}:
            terminal = event.kind
            trace = event.trace
    if terminal is ModelStreamKind.CANCELLED:
        raise GenerativeForgeError("geração estruturada cancelada")
    if terminal is not ModelStreamKind.COMPLETED or trace is None:
        raise GenerativeForgeError("geração estruturada falhou de modo seguro")
    raw = "".join(fragments)
    raw_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if len(raw.encode("utf-8")) > 256 * 1024:
        raise StructuredGenerationError(
            "saída estruturada excedeu o limite",
            trace=trace,
            raw_sha256=raw_sha256,
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StructuredGenerationError(
            "runtime não produziu JSON válido",
            trace=trace,
            raw_sha256=raw_sha256,
        ) from error
    if not isinstance(payload, dict):
        raise StructuredGenerationError(
            "saída estruturada precisa ser objeto",
            trace=trace,
            raw_sha256=raw_sha256,
        )
    return StructuredGeneration(payload, trace, raw_sha256)


INTENT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "minLength": 1, "maxLength": 2048},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "operations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "remove"]},
                    "path": {
                        "type": "string",
                        "pattern": "^(identity|purpose|behavior|interface|data|output|constraints)(\\.[A-Za-z0-9_-]{1,64}){1,5}$",
                    },
                    "value": {},
                },
                "required": ["action", "path", "value"],
                "additionalProperties": False,
            },
        },
        "requested_capabilities": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string", "minLength": 3, "maxLength": 96},
        },
    },
    "required": ["rationale", "confidence", "operations", "requested_capabilities"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class GenerativeIntentPlan:
    delta: IntentDelta
    requested_capabilities: tuple[str, ...]
    generation_trace: StochasticTrace
    raw_sha256: str


class IntentPlanner:
    def __init__(self, runtime: LocalModelRuntime, policy: SamplingPolicy | None = None) -> None:
        self.runtime = runtime
        self.policy = policy or initial_sampling_policies()["planning"]

    def propose(
        self,
        aggregate: CreationAggregate,
        *,
        source_event_id: str,
        utterance: str,
        cancellation: CancellationToken,
    ) -> GenerativeIntentPlan:
        if not source_event_id or not utterance.strip():
            raise GenerativeForgeError("planejamento exige fala e proveniência")
        prompt = (
            "Transforme a fala em uma proposta de alteração da CreationSpec. "
            "Use paths pontuados (ex.: behavior.autonomy) sob identity, purpose, behavior, interface, data, output ou constraints. "
            "Nunca escreva capabilities, grants, schema, creation_id ou version nas operações. "
            "Liste capabilities apenas como pedidos sem autoridade. Não confirme a proposta.\n\n"
            f"CreationSpec atual:\n{json.dumps(aggregate.current.to_dict(), ensure_ascii=False, sort_keys=True)}\n\n"
            f"Fala humana:\n{utterance}"
        )
        generated = generate_structured(
            self.runtime,
            operation_id=f"intent:{source_event_id}",
            messages=(
                ChatMessage("system", "/no_think\nVocê planeja mudanças, mas não concede permissões nem aprovação."),
                ChatMessage("user", prompt),
            ),
            policy=self.policy,
            schema=INTENT_PLAN_SCHEMA,
            cancellation=cancellation,
        )
        value = generated.payload
        if set(value) != {"rationale", "confidence", "operations", "requested_capabilities"}:
            raise GenerativeForgeError("plano contém campos não autorizados")
        raw_operations = value["operations"]
        if not isinstance(raw_operations, list) or not 1 <= len(raw_operations) <= 12:
            raise GenerativeForgeError("plano precisa de operações limitadas")
        operations: list[IntentOperation] = []
        allowed_roots = {"identity", "purpose", "behavior", "interface", "data", "output", "constraints"}
        for raw in raw_operations:
            if not isinstance(raw, dict) or set(raw) != {"action", "path", "value"}:
                raise GenerativeForgeError("operação generativa inválida")
            raw_path = raw["path"]
            if not isinstance(raw_path, str):
                raise GenerativeForgeError("path generativo precisa ser string pontuada")
            path = raw_path.split(".")
            if not 2 <= len(path) <= 6 or path[0] not in allowed_roots:
                raise GenerativeForgeError("path generativo fora do domínio permitido")
            if any(not isinstance(part, str) or not part or len(part) > 64 for part in path):
                raise GenerativeForgeError("componente de path generativo inválido")
            action = raw["action"]
            if action not in {"set", "remove"}:
                raise GenerativeForgeError("ação generativa inválida")
            operations.append(IntentOperation(action, tuple(path), raw.get("value")))
        requested = value["requested_capabilities"]
        if not isinstance(requested, list) or len(requested) > 16 or any(
            not isinstance(item, str) or not item.strip() for item in requested
        ):
            raise GenerativeForgeError("pedidos de capability inválidos")
        # Deduplica sem promover pedido a grant.
        requested_capabilities = tuple(dict.fromkeys(item.strip() for item in requested))
        confidence = value["confidence"]
        rationale = value["rationale"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise GenerativeForgeError("confidence generativa inválida")
        if not isinstance(rationale, str) or not rationale.strip():
            raise GenerativeForgeError("rationale generativa ausente")
        delta_id = f"intent:gen:{generated.raw_sha256[:24]}"
        delta = IntentDelta(
            delta_id,
            aggregate.current.creation_id,
            aggregate.current.version,
            tuple(operations),
            rationale.strip(),
            (source_event_id,),
            float(confidence),
            DeltaConfirmation.PROPOSED,
            tuple(item.path for item in operations),
        )
        return GenerativeIntentPlan(delta, requested_capabilities, generated.trace, generated.raw_sha256)


T_SOURCE_PATTERN = (
    r'^language T/1\.1\nmodule [a-z][a-z0-9_.]*\n\n'
    r'capability manifest\n\nfield [A-Z][A-Za-z0-9_]*\n'
    r'  trace value: Text\n\ncondense [A-Z][A-Za-z0-9_]* in [A-Z][A-Za-z0-9_]*\n'
    r'  effects \[manifest\]\n  emit (value|"[^"\n]{1,200}")\n?$'
)

T_PROJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "string", "pattern": "^[a-z][a-z0-9_.-]{0,63}$"},
                    "module": {"type": "string", "pattern": r"^[a-z][a-z0-9_.]*$"},
                    "field_name": {"type": "string", "pattern": r"^[A-Z][A-Za-z0-9_]*$"},
                    "operation_name": {"type": "string", "pattern": r"^[A-Z][A-Za-z0-9_]*$"},
                    "emit_literal": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r'^[^"\\\n\r]+$'},
                    "watch_paths": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string"}},
                    },
                },
                "required": ["unit_id", "module", "field_name", "operation_name", "emit_literal", "watch_paths"],
                "additionalProperties": False,
            },
        },
        "tests": {
            "type": "array", "minItems": 2, "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "unit_id": {"type": "string", "pattern": "^[a-z][a-z0-9_.-]{0,63}$"},
                    "input": {"type": "string"},
                    "expected_contains": {"type": "string", "minLength": 1, "maxLength": 48},
                },
                "required": ["name", "unit_id", "input", "expected_contains"],
                "additionalProperties": False,
            },
        },
        "entry_unit": {"type": "string"},
    },
    "required": ["units", "tests", "entry_unit"],
    "additionalProperties": False,
}

T_UNIT_REVISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "emit_literal": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r'^[^"\\\n\r]+$'},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1024},
    },
    "required": ["emit_literal", "rationale"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class GeneratedTProject:
    project_id: str
    creation_sha256: str
    units: tuple[ForgeUnit, ...]
    tests: tuple[dict[str, str], ...]
    entry_unit: str
    generation_trace: StochasticTrace
    raw_sha256: str
    candidate_rejections: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledTProject:
    project: GeneratedTProject
    forge_receipt: ForgeReceipt
    tcap: bytes
    tcap_sha256: str


MAX_EMIT_LITERAL_CHARS = 200
MAX_GENERATED_EXPECTATION_CHARS = 48
MAX_GENERATED_EXPECTATIONS_PER_UNIT_CHARS = 120


def validate_project_test_feasibility(
    project: GeneratedTProject,
    *,
    external_tests: tuple[dict[str, str], ...] = (),
) -> None:
    """Prova que um único emit_literal pode satisfazer os substrings declarados."""
    expected_by_unit: dict[str, list[str]] = {}
    for test in (*project.tests, *external_tests):
        unit_id = test["unit_id"]
        expected = test["expected_contains"]
        if any(char in expected for char in ('"', "\\", "\n", "\r")):
            raise GenerativeForgeError("expected_contains não cabe na gramática T segura")
        values = expected_by_unit.setdefault(unit_id, [])
        if expected not in values:
            values.append(expected)
    for unit_id, values in expected_by_unit.items():
        if len(",".join(values)) > MAX_EMIT_LITERAL_CHARS:
            raise GenerativeForgeError(
                f"testes da unidade {unit_id} são insatisfatíveis pelo emit_literal"
            )


class TProgramSynthesizer:
    def __init__(
        self,
        runtime: LocalModelRuntime,
        policy: SamplingPolicy | None = None,
        *,
        synthesis_candidate_budget: int = 2,
        revision_candidate_budget: int = 3,
    ) -> None:
        if not 1 <= synthesis_candidate_budget <= 3:
            raise GenerativeForgeError("budget de candidatos de síntese fora do limite")
        if not 1 <= revision_candidate_budget <= 3:
            raise GenerativeForgeError("budget de candidatos de revisão fora do limite")
        self.runtime = runtime
        self.synthesis_candidate_budget = synthesis_candidate_budget
        self.revision_candidate_budget = revision_candidate_budget
        default = initial_sampling_policies()["code"]
        self.policy = policy or SamplingPolicy(
            default.policy_id,
            default.temperature,
            default.top_p,
            default.top_k,
            default.min_p,
            default.repeat_penalty,
            1536,
        )

    def synthesize(
        self,
        creation: CreationSpec,
        *,
        source_event_ids: tuple[str, ...],
        cancellation: CancellationToken,
    ) -> GeneratedTProject:
        if not source_event_ids:
            raise GenerativeForgeError("síntese T exige proveniência")
        grammar = """Gere uma AST T/1.1 mínima por unidade: module, field_name,
operation_name e emit_literal. O lowering determinístico adicionará capability
manifest, trace value: Text, effects [manifest] e emit. Escolha nomes e mensagens
que representem de fato a CreationSpec. Não invente imports. Gere 2 a 4 unidades
com responsabilidades distintas. A topologia acíclica será derivada pelo Casulo.
"""
        prompt = (
            f"{grammar}\nCreationSpec confirmada:\n"
            f"{json.dumps(creation.to_dict(), ensure_ascii=False, sort_keys=True)}\n"
            "Gere units, testes comportamentais e entry_unit. O código deve refletir a criação, não um exemplo genérico. "
            f"Cada expected_contains deve ser substring literal curto de até {MAX_GENERATED_EXPECTATION_CHARS} caracteres; "
            f"por unidade, todos combinados devem ocupar até {MAX_GENERATED_EXPECTATIONS_PER_UNIT_CHARS} caracteres. "
            "Não serialize objetos, schemas ou a CreationSpec em expected_contains."
        )
        rejected: list[dict[str, Any]] = []
        for candidate_index in range(self.synthesis_candidate_budget):
            try:
                generated = generate_structured(
                    self.runtime,
                    operation_id=(
                        f"tforge:{creation.creation_id}:{creation.version}:candidate-{candidate_index}"
                    ),
                    messages=(
                        ChatMessage("system", "/no_think\nVocê sintetiza código T candidato; compilador e capabilities são autoridades externas."),
                        ChatMessage("user", prompt),
                    ),
                    policy=self.policy,
                    schema=T_PROJECT_SCHEMA,
                    cancellation=cancellation,
                )
            except StructuredGenerationError as error:
                rejected.append(
                    {
                        "operation_id": error.trace.operation_id,
                        "phase": "synthesis",
                        "reason": "saída_estruturada_inválida",
                        "raw_sha256": error.raw_sha256,
                        "trace": error.trace.to_dict(),
                    }
                )
                continue
            try:
                project = self._project_from_payload(creation, generated)
                validate_project_test_feasibility(project)
                # O JSON Schema limita a forma externa; somente o frontend T e
                # o Forge podem aprovar símbolos, semântica, IR e grafo.
                TForge().compile(project.units)
            except PlatformError as error:
                rejected.append(
                    {
                        "operation_id": generated.trace.operation_id,
                        "phase": "synthesis",
                        "reason": "projeto_T_reprovado",
                        "error_class": type(error).__name__,
                        "raw_sha256": generated.raw_sha256,
                        "trace": generated.trace.to_dict(),
                    }
                )
                continue
            return replace(project, candidate_rejections=tuple(rejected))
        raise GenerativeForgeError(
            f"candidatos de síntese T esgotados ({len(rejected)}/{self.synthesis_candidate_budget})"
        )

    def revise_unit(
        self,
        project: GeneratedTProject,
        *,
        unit_id: str,
        correction: str,
        declared_affected_paths: tuple[tuple[str, ...], ...],
        source_event_id: str,
        cancellation: CancellationToken,
    ) -> GeneratedTProject:
        by_id = {unit.unit_id: unit for unit in project.units}
        unit = by_id.get(unit_id)
        if unit is None or not correction.strip() or not source_event_id:
            raise GenerativeForgeError("correção T inválida")
        if not any(
            _paths_intersect(watch, affected)
            for watch in unit.watch_paths
            for affected in declared_affected_paths
        ):
            raise GenerativeForgeError("unidade alvo não pertence aos affected paths")
        prompt = f"""Corrija somente o emit_literal da AST T abaixo. Não altere
module, field, operação, topologia, dependências, capabilities ou watch_paths.
A mudança precisa ser real e limitada. Quando a solicitação contiver
must_preserve_all_test_expectations, o novo emit_literal deve conter todos os
expected_contains listados, não apenas o que falhou.
O emit_literal deve ser texto simples entre 1 e 200 caracteres, sem aspas,
barra invertida ou quebra de linha. Não copie a sintaxe T para esse campo.

Solicitação de correção verificada: {correction}
Affected paths: {json.dumps(declared_affected_paths, ensure_ascii=False)}
Source T atual:
{unit.source}
"""
        module, field_name, operation_name = _read_lowered_unit(unit.source)
        generated: StructuredGeneration | None = None
        revised: ForgeUnit | None = None
        rejected: list[dict[str, Any]] = []
        revision_policy = replace(
            self.policy,
            max_generated_tokens=min(self.policy.max_generated_tokens, 384),
        )
        for candidate_index in range(self.revision_candidate_budget):
            try:
                candidate = generate_structured(
                    self.runtime,
                    operation_id=f"trevise:{source_event_id}:candidate-{candidate_index}",
                    messages=(
                        ChatMessage("system", "/no_think\nVocê revisa uma unidade T candidata; não amplia escopo nem capabilities."),
                        ChatMessage("user", prompt),
                    ),
                    policy=revision_policy,
                    schema=T_UNIT_REVISION_SCHEMA,
                    cancellation=cancellation,
                )
            except StructuredGenerationError as error:
                rejected.append(
                    {
                        "operation_id": error.trace.operation_id,
                        "reason": "saída_estruturada_inválida",
                        "raw_sha256": error.raw_sha256,
                        "trace": error.trace.to_dict(),
                    }
                )
                continue
            reason = ""
            emit_literal: object = None
            if set(candidate.payload) != {"emit_literal", "rationale"}:
                reason = "campos_não_autorizados"
            else:
                emit_literal = candidate.payload["emit_literal"]
                if (
                    not isinstance(emit_literal, str)
                    or not emit_literal
                    or len(emit_literal) > 200
                    or any(char in emit_literal for char in ('"', "\\", "\n", "\r"))
                ):
                    reason = "emit_literal_inválido"
            candidate_unit: ForgeUnit | None = None
            if not reason and isinstance(emit_literal, str):
                revised_source = lower_generated_unit_to_t(
                    module, field_name, operation_name, emit_literal
                )
                if revised_source == unit.source:
                    reason = "revisão_sem_mudança"
                else:
                    candidate_unit = ForgeUnit(
                        unit.unit_id, revised_source, unit.watch_paths, unit.dependencies
                    )
                    checked = check_source(
                        candidate_unit.source, file=f"<revised:{unit.unit_id}>"
                    )
                    if not checked.ok:
                        reason = "revisão_não_compila"
            if reason:
                rejected.append(
                    {
                        "operation_id": candidate.trace.operation_id,
                        "reason": reason,
                        "raw_sha256": candidate.raw_sha256,
                        "trace": candidate.trace.to_dict(),
                    }
                )
                continue
            generated = candidate
            revised = candidate_unit
            break
        if generated is None or revised is None:
            raise CandidateBudgetExhausted(
                "revisão", self.revision_candidate_budget, tuple(rejected)
            )
        updated = tuple(revised if item.unit_id == unit_id else item for item in project.units)
        result = GeneratedTProject(
            f"t-project:{generated.raw_sha256[:24]}",
            project.creation_sha256,
            updated,
            project.tests,
            project.entry_unit,
            generated.trace,
            generated.raw_sha256,
            (*project.candidate_rejections, *rejected),
        )
        verify_correction_scope(project, result, declared_affected_paths=declared_affected_paths)
        return result

    @staticmethod
    def _project_from_payload(creation: CreationSpec, generated: StructuredGeneration) -> GeneratedTProject:
        value = generated.payload
        if set(value) != {"units", "tests", "entry_unit"}:
            raise GenerativeForgeError("projeto T contém campos não autorizados")
        raw_units = value["units"]
        if not isinstance(raw_units, list) or not 2 <= len(raw_units) <= 4:
            raise GenerativeForgeError("projeto T precisa de 2 a 4 unidades")
        units: list[ForgeUnit] = []
        for raw in raw_units:
            expected = {"unit_id", "module", "field_name", "operation_name", "emit_literal", "watch_paths"}
            if not isinstance(raw, dict) or set(raw) != expected:
                raise GenerativeForgeError("unidade T generativa inválida")
            try:
                source = lower_generated_unit_to_t(
                    str(raw["module"]),
                    str(raw["field_name"]),
                    str(raw["operation_name"]),
                    str(raw["emit_literal"]),
                )
            except GenerativeForgeError:
                raise
            try:
                unit = ForgeUnit(
                    str(raw["unit_id"]),
                    source,
                    tuple(tuple(str(part) for part in path) for path in raw["watch_paths"]),
                    () if not units else (units[-1].unit_id,),
                )
            except (TypeError, ValueError, PlatformError) as error:
                raise GenerativeForgeError("contrato da unidade T reprovado") from error
            units.append(unit)
        if len({unit.unit_id for unit in units}) != len(units):
            raise GenerativeForgeError("unit_id duplicado")
        tests = value["tests"]
        if not isinstance(tests, list) or not 2 <= len(tests) <= 6:
            raise GenerativeForgeError("testes generativos ausentes")
        normalized_tests: list[dict[str, str]] = []
        for test in tests:
            if not isinstance(test, dict) or set(test) != {"name", "unit_id", "input", "expected_contains"}:
                raise GenerativeForgeError("teste generativo inválido")
            normalized = {key: str(test[key]).strip() for key in test}
            if any(not item for item in normalized.values()):
                raise GenerativeForgeError("teste generativo vazio")
            if normalized["unit_id"] not in {unit.unit_id for unit in units}:
                raise GenerativeForgeError("teste referencia unidade inexistente")
            if len(normalized["expected_contains"]) > MAX_GENERATED_EXPECTATION_CHARS:
                raise GenerativeForgeError("expected_contains generativo excede o limite")
            normalized_tests.append(normalized)
        entry = str(value["entry_unit"])
        if entry not in {unit.unit_id for unit in units}:
            raise GenerativeForgeError("entry_unit não existe")
        result = GeneratedTProject(
            f"t-project:{generated.raw_sha256[:24]}",
            canonical_sha256(creation.to_dict()),
            tuple(units),
            tuple(normalized_tests),
            entry,
            generated.trace,
            generated.raw_sha256,
        )
        by_unit: dict[str, list[str]] = {}
        for test in result.tests:
            values = by_unit.setdefault(test["unit_id"], [])
            if test["expected_contains"] not in values:
                values.append(test["expected_contains"])
        if any(
            len(",".join(values)) > MAX_GENERATED_EXPECTATIONS_PER_UNIT_CHARS
            for values in by_unit.values()
        ):
            raise GenerativeForgeError("expectativas generativas por unidade excedem a reserva")
        return result


def compile_generated_project(
    project: GeneratedTProject,
    forge: TForge | None = None,
    *,
    affected_paths: tuple[tuple[str, ...], ...] = (),
) -> CompiledTProject:
    compiler = forge or TForge()
    receipt = compiler.compile(project.units, affected_paths=affected_paths)
    segments: list[TcapSegment] = [TcapSegment("code", b"\xC3", "rx", alignment=16)]
    capabilities: set[str] = set()
    for index, unit in enumerate(project.units):
        checked = check_source(unit.source, file=f"<generated:{unit.unit_id}>")
        if not checked.ok or checked.ir is None or checked.graph is None:
            raise GenerativeForgeError("unidade aprovada pelo Forge não recompilou")
        capabilities.update(checked.ir.capabilities)
        segments.extend(
            (
                TcapSegment(f"source.{index}", unit.source.encode("utf-8"), "r"),
                TcapSegment(f"ir.{index}", _canonical(checked.ir.to_dict()), "r"),
                TcapSegment(f"graph.{index}", _canonical(checked.graph.to_dict()), "r"),
            )
        )
    resource = ResourceContract(
        memory_limit_bytes=16 * 1024 * 1024,
        arena_bytes=2 * 1024 * 1024,
        max_threads=1,
        semantic_class=SemanticClass.FLOW,
        deterministic=True,
        numerical_precision="integer",
        permissions=("memory", "console"),
        quality_definition={"protocol": "casulo-generated-agent-correctness/1"},
        residual_routing={"invalid": "QUARANTINE"},
    )
    raw = build_tcap(
        segments=tuple(segments),
        target="x86_64-casulo-none",
        abi="casulo-syscall/0.1",
        entry_segment="code",
        entry_offset=0,
        compiler={"name": "casulo-t", "version": "0.25.0a1", "commit": "worktree"},
        resource_contract=resource,
        capability_requirements=tuple(sorted(capabilities)),
    )
    parse_tcap(raw)
    return CompiledTProject(project, receipt, raw, hashlib.sha256(raw).hexdigest())


def verify_correction_scope(
    before: GeneratedTProject,
    after: GeneratedTProject,
    *,
    declared_affected_paths: tuple[tuple[str, ...], ...],
) -> tuple[str, ...]:
    before_map = {unit.unit_id: unit for unit in before.units}
    after_map = {unit.unit_id: unit for unit in after.units}
    if set(before_map) != set(after_map):
        raise GenerativeForgeError("correção alterou a topologia de unidades")
    changed = tuple(
        unit_id for unit_id in sorted(before_map)
        if before_map[unit_id].source != after_map[unit_id].source
    )
    if not changed:
        raise GenerativeForgeError("correção não alterou código")
    for unit_id in changed:
        unit = after_map[unit_id]
        if not any(
            _paths_intersect(watch, affected)
            for watch in unit.watch_paths
            for affected in declared_affected_paths
        ):
            raise GenerativeForgeError("source diff escapou dos affected paths")
    return changed


def _paths_intersect(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    common = min(len(left), len(right))
    return left[:common] == right[:common]


_LOWERED_UNIT_RE = re.compile(
    r'^language T/1\.1\nmodule (?P<module>[a-z][a-z0-9_.]*)\n\n'
    r'capability manifest\n\nfield (?P<field>[A-Z][A-Za-z0-9_]*)\n'
    r'  trace value: Text\n\ncondense (?P<operation>[A-Z][A-Za-z0-9_]*) in (?P=field)\n'
    r'  effects \[manifest\]\n  emit "(?P<emit>[^"\n]{1,200})"\n$'
)


def lower_generated_unit_to_t(module: str, field_name: str, operation_name: str, emit_literal: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_.]*", module):
        raise GenerativeForgeError("module da AST T é inválido")
    if not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", field_name):
        raise GenerativeForgeError("field da AST T é inválido")
    if not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", operation_name):
        raise GenerativeForgeError("operação da AST T é inválida")
    if not emit_literal or len(emit_literal) > 200 or any(
        char in emit_literal for char in ('"', "\\", "\n", "\r")
    ):
        raise GenerativeForgeError("emit_literal da AST T é inválido")
    source = (
        f"language T/1.1\nmodule {module}\n\ncapability manifest\n\n"
        f"field {field_name}\n  trace value: Text\n\n"
        f"condense {operation_name} in {field_name}\n  effects [manifest]\n"
        f"  emit \"{emit_literal}\"\n"
    )
    if _LOWERED_UNIT_RE.fullmatch(source) is None:
        raise GenerativeForgeError("lowering da AST T violou a gramática")
    return source


def _read_lowered_unit(source: str) -> tuple[str, str, str]:
    match = _LOWERED_UNIT_RE.fullmatch(source)
    if match is None:
        raise GenerativeForgeError("source T não pertence ao lowering generativo")
    return match.group("module"), match.group("field"), match.group("operation")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
