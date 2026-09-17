from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

from casulo.product.domain import DomainError
from casulo.product.creative_interlocution import validate_experiential_question
from casulo.product.engine_contracts import CancellationToken
from casulo.product.intent_reconstruction import (
    EpistemicGap,
    HypothesisImpactStatus,
    HypothesisRequirementImpact,
    IntentEvidenceKind,
    IntentHypothesis,
    IntentObservation,
    IntentStakes,
    IntentTaskKind,
    IntentTwin,
)
from casulo.product.neural_budget import NeuralOperation, NeuralRouteDecision
from casulo.product.revolution_contracts import RequirementStrength

from .generative_forge import GenerativeForgeError, StructuredGeneration, generate_structured
from .local_model_runtime import ChatMessage, LocalModelRuntime, SamplingPolicy, StochasticTrace, initial_sampling_policies
from .neural_budgeting import budgeted_policy, validate_budgeted_messages


_PATH_PATTERN = "^[A-Za-z][A-Za-z0-9_-]*(\\.[A-Za-z][A-Za-z0-9_-]*){0,5}$"
_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "statement": {"type": "string", "minLength": 1, "maxLength": 1200},
        "evidence_kind": {"type": "string", "enum": ["EXPLICIT", "INFERRED"]},
        "strength": {"type": "string", "enum": ["HARD", "SOFT"]},
        "affected_paths": {
            "type": "array", "minItems": 1, "maxItems": 4,
            "items": {"type": "string", "pattern": _PATH_PATTERN},
        },
        "verifier_kind": {
            "type": "string",
            "enum": ["compile", "simulation", "clean-execution", "domain-invariant", "human-review"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["statement", "evidence_kind", "strength", "affected_paths", "verifier_kind", "confidence"],
    "additionalProperties": False,
}

INTENT_RECONSTRUCTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 1600},
        "task_kind": {"type": "string", "enum": ["CONVERSATION", "EXPLORATION", "CREATION"]},
        "stakes": {"type": "string", "enum": ["LOW", "MATERIAL", "HIGH"]},
        "observations": {"type": "array", "minItems": 1, "maxItems": 8, "items": _OBSERVATION_SCHEMA},
        "hypotheses": {
            "type": "array", "minItems": 1, "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "interpretation": {"type": "string", "minLength": 1, "maxLength": 1200},
                    "decision_dimension": {"type": "string", "minLength": 1, "maxLength": 160},
                    "choice_value": {"type": "string", "minLength": 1, "maxLength": 300},
                    "excludes_choice_value": {"type": "string", "minLength": 1, "maxLength": 300},
                    "consequences": {
                        "type": "array", "minItems": 1, "maxItems": 5,
                        "items": {"type": "string", "minLength": 1, "maxLength": 600},
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "supporting_observation_indices": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {"type": "integer", "minimum": 0, "maximum": 7},
                    },
                    "requirement_impacts": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "observation_index": {"type": "integer", "minimum": 0, "maximum": 7},
                                "status": {"type": "string", "enum": ["PRESERVES", "CHANGES", "CONFLICTS", "UNKNOWN"]},
                                "rationale": {"type": "string", "minLength": 1, "maxLength": 500},
                            },
                            "required": ["observation_index", "status", "rationale"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["interpretation", "decision_dimension", "choice_value", "excludes_choice_value", "consequences", "confidence", "supporting_observation_indices", "requirement_impacts"],
                "additionalProperties": False,
            },
        },
        "material_gap": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "minLength": 1, "maxLength": 700},
                        "why_material": {"type": "string", "minLength": 1, "maxLength": 700},
                        "affected_paths": {
                            "type": "array", "minItems": 1, "maxItems": 4,
                            "items": {"type": "string", "pattern": _PATH_PATTERN},
                        },
                        "information_gain": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["question", "why_material", "affected_paths", "information_gain"],
                    "additionalProperties": False,
                },
            ]
        },
        "selected_hypothesis_index": {"anyOf": [{"type": "null"}, {"type": "integer", "minimum": 0, "maximum": 1}]},
    },
    "required": ["summary", "task_kind", "stakes", "observations", "hypotheses", "material_gap", "selected_hypothesis_index"],
    "additionalProperties": False,
}

INTENT_REFINEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "refined_summary": {"type": "string", "minLength": 1, "maxLength": 1600},
        "selected_hypothesis_index": {"type": "integer", "minimum": 0, "maximum": 1},
        "additional_observations": {"type": "array", "minItems": 0, "maxItems": 5, "items": _OBSERVATION_SCHEMA},
        "hypothesis_impacts": {
            "type": "array", "minItems": 1, "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "hypothesis_index": {"type": "integer", "minimum": 0, "maximum": 1},
                    "requirement_impacts": {
                        "type": "array", "minItems": 1, "maxItems": 13,
                        "items": {
                            "type": "object",
                            "properties": {
                                "observation_index": {"type": "integer", "minimum": 0, "maximum": 12},
                                "status": {"type": "string", "enum": ["PRESERVES", "CHANGES", "CONFLICTS", "UNKNOWN"]},
                                "rationale": {"type": "string", "minLength": 1, "maxLength": 500},
                            },
                            "required": ["observation_index", "status", "rationale"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["hypothesis_index", "requirement_impacts"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["refined_summary", "selected_hypothesis_index", "additional_observations", "hypothesis_impacts"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class IntentReconstruction:
    twin: IntentTwin
    trace: StochasticTrace
    raw_sha256: str
    model_task_kind: IntentTaskKind
    route_decisions: tuple[NeuralRouteDecision, ...]
    deterministic_overrides: tuple[str, ...] = ()
    candidate_rejections: tuple[dict[str, Any], ...] = ()


def _paths(values: Any) -> tuple[tuple[str, ...], ...]:
    if not isinstance(values, list) or not 1 <= len(values) <= 4:
        raise GenerativeForgeError("reconstrução exige affected_paths limitados")
    paths: list[tuple[str, ...]] = []
    for value in values:
        if not isinstance(value, str):
            raise GenerativeForgeError("affected_path precisa ser pontuado")
        parts = tuple(value.split("."))
        if not parts or len(parts) > 6 or any(not part or len(part) > 64 for part in parts):
            raise GenerativeForgeError("affected_path generativo inválido")
        paths.append(parts)
    return tuple(paths)


def _strict_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise GenerativeForgeError(f"{field_name} deve estar entre 0 e 1")
    return float(value)


def _observation(
    raw: Any,
    *,
    observation_id: str,
    source_event_ids: tuple[str, ...],
) -> IntentObservation:
    required = {"statement", "evidence_kind", "strength", "affected_paths", "verifier_kind", "confidence"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise GenerativeForgeError("observação neural não corresponde ao contrato")
    try:
        kind = IntentEvidenceKind(raw["evidence_kind"])
        strength = RequirementStrength(raw["strength"])
    except (TypeError, ValueError) as error:
        raise GenerativeForgeError("classificação de observação inválida") from error
    statement = raw["statement"]
    verifier_kind = raw["verifier_kind"]
    if not isinstance(statement, str) or not statement.strip():
        raise GenerativeForgeError("observação sem enunciado")
    if verifier_kind not in {"compile", "simulation", "clean-execution", "domain-invariant", "human-review"}:
        raise GenerativeForgeError("verificador proposto não autorizado")
    # O modelo escolhe uma classe fechada; a identidade do verificador é determinística.
    selected_verifier = f"verifier:{verifier_kind}"
    # Todo requisito HARD precisa também atravessar o teste de aceite humano
    # anexado ao projeto; compilar sozinho nunca demonstra cumprimento semântico.
    verifier_ids = tuple(
        dict.fromkeys(
            ("verifier:acceptance", selected_verifier)
            if strength is RequirementStrength.HARD
            else (selected_verifier,)
        )
    )
    return IntentObservation(
        observation_id,
        statement.strip(),
        kind,
        strength,
        source_event_ids,
        _paths(raw["affected_paths"]),
        verifier_ids,
        _strict_number(raw["confidence"], field_name="confidence"),
    )


class IntentReconstructionEngine:
    """Neural hypothesis formation bounded by a deterministic, auditable contract."""

    def __init__(
        self,
        runtime: LocalModelRuntime,
        policy: SamplingPolicy | None = None,
        *,
        candidate_budget: int = 2,
    ) -> None:
        if not 1 <= candidate_budget <= 3:
            raise GenerativeForgeError("budget de reconstrução precisa ficar entre um e três")
        self.runtime = runtime
        self.policy = policy
        self.candidate_budget = candidate_budget

    def propose(
        self,
        *,
        creation_id: str,
        source_event_id: str,
        utterance: str,
        expected_behavior: str,
        cancellation: CancellationToken,
        task_kind_hint: IntentTaskKind | None = None,
    ) -> IntentReconstruction:
        if not creation_id or not source_event_id or not utterance.strip():
            raise GenerativeForgeError("reconstrução exige criação, fala e proveniência")
        prompt = (
            "Reconstrua a intenção, não produza a solução. Extraia somente o que foi dito como EXPLICIT; "
            "marque toda consequência deduzida como INFERRED. Formule uma hipótese quando a intenção estiver clara; "
            "use duas somente quando existir uma bifurcação material real. Com duas, elas precisam disputar a mesma "
            "decision_dimension e ter choice_value mutuamente exclusivos. "
            "Em cada hipótese, excludes_choice_value deve ser exatamente o choice_value da outra. Paráfrases ou escolhas "
            "que podem coexistir são inválidas. Em requirement_impacts, classifique cada observação exatamente uma vez; "
            "toda hipótese selecionável precisa PRESERVAR cada observação HARD. Faça no máximo uma pergunta: somente a lacuna com maior ganho de informação que mudaria materialmente "
            "comportamento, segurança ou critério de aceite. A pergunta deve ser sobre experiência, prioridade, autonomia, risco ou gosto observável. "
            "Nunca transfira ao usuário escolhas de linguagem, framework, API, banco, arquitetura, algoritmo, modelo, infraestrutura, servidor ou hardware; resolva isso internamente. "
            "Use palavras que uma pessoa sem formação técnica entenda. Se nada material falta, use material_gap=null "
            "e selecione a hipótese mais sustentada. Não conceda capabilities e não diga que algo foi implementado.\n\n"
            f"Pedido humano:\n{utterance.strip()}\n\n"
            f"Comportamento observável desejado:\n{expected_behavior.strip() or '(não informado)'}\n\n"
            f"Contexto determinístico da interface:\n{task_kind_hint.value if task_kind_hint else '(nenhum)'}"
        )
        system = ChatMessage(
            "system",
            "/no_think\nVocê reconstrói intenção sob incerteza explícita; não cria aprovação nem grant.",
        )
        route_decision, routed_policy = budgeted_policy(
            NeuralOperation.INTENT_RECONSTRUCTION,
            source_event_ids=(source_event_id,),
            policy_override=self.policy,
        )
        user_prompt = prompt
        rejections: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for attempt in range(1, self.candidate_budget + 1):
            messages = (system, ChatMessage("user", user_prompt))
            validate_budgeted_messages(route_decision, messages)
            generated = generate_structured(
                self.runtime,
                operation_id=f"intent-twin:{source_event_id}:candidate-{attempt}",
                messages=messages,
                policy=routed_policy,
                schema=INTENT_RECONSTRUCTION_SCHEMA,
                cancellation=cancellation,
            )
            try:
                twin, model_task_kind, overrides = self._parse_initial(
                    generated,
                    creation_id=creation_id,
                    source_event_id=source_event_id,
                    task_kind_hint=task_kind_hint,
                )
            except (DomainError, GenerativeForgeError) as error:
                last_error = error
                rejection = {
                    "attempt": attempt,
                    "raw_sha256": generated.raw_sha256,
                    "diagnostic_type": type(error).__name__,
                    "diagnostic": str(error),
                    "payload_sha256": hashlib.sha256(
                        json.dumps(generated.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                }
                rejections.append(rejection)
                if attempt == self.candidate_budget:
                    break
                user_prompt = (
                    prompt
                    + "\n\nO candidato anterior foi recusado pelo contrato determinístico. "
                    "Produza o objeto completo novamente; não explique o erro fora do JSON.\n"
                    + f"Diagnóstico real: {error}\n"
                    + "Candidato recusado:\n"
                    + json.dumps(generated.payload, ensure_ascii=False, sort_keys=True)
                )
                continue
            return IntentReconstruction(
                twin,
                generated.trace,
                generated.raw_sha256,
                model_task_kind,
                (route_decision,),
                overrides,
                tuple(rejections),
            )
        raise GenerativeForgeError(
            f"reconstrução esgotou {self.candidate_budget} candidatos: {last_error}"
        )

    def refine(
        self,
        reconstruction: IntentReconstruction,
        *,
        answer: str,
        source_event_id: str,
        cancellation: CancellationToken,
    ) -> IntentReconstruction:
        twin = reconstruction.twin
        if len(twin.open_gaps) != 1 or not answer.strip():
            raise GenerativeForgeError("refino exige exatamente uma lacuna aberta e resposta")
        prompt = (
            "A resposta humana abaixo resolve a pergunta material. Escolha uma das duas hipóteses existentes, "
            "refine o resumo e extraia apenas consequências novas. A resposta é evidência humana; derivações devem "
            "continuar marcadas INFERRED. Recalcule hypothesis_impacts para todas as observações antigas e novas; "
            "a hipótese selecionada precisa PRESERVAR todas as HARD. Não invente uma terceira hipótese, capability ou aprovação.\n\n"
            f"IntentTwin:\n{json.dumps(twin.to_dict(), ensure_ascii=False, sort_keys=True)}\n\n"
            f"Resposta humana:\n{answer.strip()}"
        )
        route_decision, routed_policy = budgeted_policy(
            NeuralOperation.INTENT_REFINEMENT,
            source_event_ids=(source_event_id,),
            material_gap_open=True,
            policy_override=self.policy,
        )
        messages = (
            ChatMessage("system", "/no_think\nVocê reduz incerteza sem confundir inferência com fala explícita."),
            ChatMessage("user", prompt),
        )
        validate_budgeted_messages(route_decision, messages)
        generated = generate_structured(
            self.runtime,
            operation_id=f"intent-refine:{source_event_id}",
            messages=messages,
            policy=routed_policy,
            schema=INTENT_REFINEMENT_SCHEMA,
            cancellation=cancellation,
        )
        raw = generated.payload
        if set(raw) != {"refined_summary", "selected_hypothesis_index", "additional_observations", "hypothesis_impacts"}:
            raise GenerativeForgeError("refino contém campos não autorizados")
        selected = raw["selected_hypothesis_index"]
        if isinstance(selected, bool) or not isinstance(selected, int) or not 0 <= selected < len(twin.hypotheses):
            raise GenerativeForgeError("refino selecionou hipótese inválida")
        additional_raw = raw["additional_observations"]
        if not isinstance(additional_raw, list) or len(additional_raw) > 5:
            raise GenerativeForgeError("refino excedeu observações permitidas")
        prefix = hashlib.sha256(source_event_id.encode("utf-8")).hexdigest()[:8]
        additional = tuple(
            _observation(
                item,
                observation_id=f"obs:refine:{prefix}:{index + 1}",
                source_event_ids=(source_event_id,),
            )
            for index, item in enumerate(additional_raw)
        )
        combined_observations = (*twin.observations, *additional)
        impact_sets = raw["hypothesis_impacts"]
        if not isinstance(impact_sets, list) or len(impact_sets) != len(twin.hypotheses):
            raise GenerativeForgeError("refino precisa atualizar impactos de todas as hipóteses")
        updated_hypotheses: list[IntentHypothesis | None] = [None] * len(twin.hypotheses)
        for impact_set in impact_sets:
            if not isinstance(impact_set, dict) or set(impact_set) != {"hypothesis_index", "requirement_impacts"}:
                raise GenerativeForgeError("matriz de impacto refinada inválida")
            hypothesis_index = impact_set["hypothesis_index"]
            if (
                isinstance(hypothesis_index, bool)
                or not isinstance(hypothesis_index, int)
                or not 0 <= hypothesis_index < len(twin.hypotheses)
                or updated_hypotheses[hypothesis_index] is not None
            ):
                raise GenerativeForgeError("índice de hipótese refinada inválido ou duplicado")
            impacts_raw = impact_set["requirement_impacts"]
            if not isinstance(impacts_raw, list) or len(impacts_raw) != len(combined_observations):
                raise GenerativeForgeError("refino precisa classificar todas as observações")
            impacts: list[HypothesisRequirementImpact] = []
            seen: set[int] = set()
            for impact in impacts_raw:
                if not isinstance(impact, dict) or set(impact) != {"observation_index", "status", "rationale"}:
                    raise GenerativeForgeError("impacto refinado inválido")
                observation_index = impact["observation_index"]
                if (
                    isinstance(observation_index, bool)
                    or not isinstance(observation_index, int)
                    or not 0 <= observation_index < len(combined_observations)
                    or observation_index in seen
                ):
                    raise GenerativeForgeError("impacto refinado duplicado ou fora do domínio")
                seen.add(observation_index)
                try:
                    status = HypothesisImpactStatus(impact["status"])
                except (TypeError, ValueError) as error:
                    raise GenerativeForgeError("status refinado inválido") from error
                impacts.append(
                    HypothesisRequirementImpact(
                        combined_observations[observation_index].observation_id,
                        status,
                        str(impact["rationale"]).strip(),
                    )
                )
            updated_hypotheses[hypothesis_index] = replace(
                twin.hypotheses[hypothesis_index],
                requirement_impacts=tuple(impacts),
            )
        if any(item is None for item in updated_hypotheses):
            raise GenerativeForgeError("matriz refinada incompleta")
        gap = twin.open_gaps[0]
        refined = twin.resolve_gap(
            gap.gap_id,
            answer,
            source_event_id=source_event_id,
            selected_hypothesis_id=twin.hypotheses[selected].hypothesis_id,
            refined_summary=str(raw["refined_summary"]),
            additional_observations=additional,
            updated_hypotheses=tuple(item for item in updated_hypotheses if item is not None),
        )
        return IntentReconstruction(
            refined,
            generated.trace,
            generated.raw_sha256,
            reconstruction.model_task_kind,
            (*reconstruction.route_decisions, route_decision),
            reconstruction.deterministic_overrides,
            reconstruction.candidate_rejections,
        )

    @staticmethod
    def _parse_initial(
        generated: StructuredGeneration,
        *,
        creation_id: str,
        source_event_id: str,
        task_kind_hint: IntentTaskKind | None,
    ) -> tuple[IntentTwin, IntentTaskKind, tuple[str, ...]]:
        raw = generated.payload
        expected = {"summary", "task_kind", "stakes", "observations", "hypotheses", "material_gap", "selected_hypothesis_index"}
        if set(raw) != expected:
            raise GenerativeForgeError("reconstrução contém campos não autorizados")
        observations_raw = raw["observations"]
        hypotheses_raw = raw["hypotheses"]
        if not isinstance(observations_raw, list) or not 1 <= len(observations_raw) <= 8:
            raise GenerativeForgeError("reconstrução exige observações limitadas")
        if not isinstance(hypotheses_raw, list) or not 1 <= len(hypotheses_raw) <= 2:
            raise GenerativeForgeError("reconstrução exige uma ou duas hipóteses")
        digest = generated.raw_sha256[:16]
        observations = tuple(
            _observation(
                item,
                observation_id=f"obs:{digest}:{index + 1}",
                source_event_ids=(source_event_id,),
            )
            for index, item in enumerate(observations_raw)
        )
        hypotheses: list[IntentHypothesis] = []
        for index, item in enumerate(hypotheses_raw):
            required = {"interpretation", "decision_dimension", "choice_value", "excludes_choice_value", "consequences", "confidence", "supporting_observation_indices", "requirement_impacts"}
            if not isinstance(item, dict) or set(item) != required:
                raise GenerativeForgeError("hipótese neural não corresponde ao contrato")
            indices = item["supporting_observation_indices"]
            if not isinstance(indices, list) or not indices or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0 or value >= len(observations)
                for value in indices
            ):
                raise GenerativeForgeError("hipótese referencia observação inválida")
            consequences = item["consequences"]
            if not isinstance(consequences, list) or not consequences or any(
                not isinstance(value, str) or not value.strip() for value in consequences
            ):
                raise GenerativeForgeError("hipótese exige consequências observáveis")
            impacts_raw = item["requirement_impacts"]
            if not isinstance(impacts_raw, list) or len(impacts_raw) != len(observations):
                raise GenerativeForgeError("hipótese precisa classificar cada observação exatamente uma vez")
            impacts: list[HypothesisRequirementImpact] = []
            impact_indices: set[int] = set()
            for impact in impacts_raw:
                if not isinstance(impact, dict) or set(impact) != {"observation_index", "status", "rationale"}:
                    raise GenerativeForgeError("impacto de requisito inválido")
                observation_index = impact["observation_index"]
                if (
                    isinstance(observation_index, bool)
                    or not isinstance(observation_index, int)
                    or not 0 <= observation_index < len(observations)
                    or observation_index in impact_indices
                ):
                    raise GenerativeForgeError("impacto referencia observação inválida ou duplicada")
                impact_indices.add(observation_index)
                try:
                    impact_status = HypothesisImpactStatus(impact["status"])
                except (TypeError, ValueError) as error:
                    raise GenerativeForgeError("status de impacto inválido") from error
                impacts.append(
                    HypothesisRequirementImpact(
                        observations[observation_index].observation_id,
                        impact_status,
                        str(impact["rationale"]).strip(),
                    )
                )
            hypotheses.append(
                IntentHypothesis(
                    f"hyp:{digest}:{index + 1}",
                    str(item["interpretation"]).strip(),
                    str(item["decision_dimension"]).strip(),
                    str(item["choice_value"]).strip(),
                    str(item["excludes_choice_value"]).strip(),
                    tuple(value.strip() for value in consequences),
                    _strict_number(item["confidence"], field_name="hypothesis confidence"),
                    tuple(observations[value].observation_id for value in dict.fromkeys(indices)),
                    tuple(impacts),
                )
            )
        gap_raw = raw["material_gap"]
        gaps: tuple[EpistemicGap, ...]
        if gap_raw is None:
            gaps = ()
        else:
            required_gap = {"question", "why_material", "affected_paths", "information_gain"}
            if not isinstance(gap_raw, dict) or set(gap_raw) != required_gap:
                raise GenerativeForgeError("lacuna neural não corresponde ao contrato")
            question = validate_experiential_question(str(gap_raw["question"]))
            gaps = (
                EpistemicGap(
                    f"gap:{digest}:1",
                    question,
                    str(gap_raw["why_material"]).strip(),
                    _paths(gap_raw["affected_paths"]),
                    _strict_number(gap_raw["information_gain"], field_name="information_gain"),
                    (source_event_id,),
                ),
            )
        selection = raw["selected_hypothesis_index"]
        if gap_raw is not None and selection is not None:
            raise GenerativeForgeError("hipótese não pode ser congelada antes de resolver lacuna material")
        if gap_raw is None and (
            isinstance(selection, bool)
            or not isinstance(selection, int)
            or not 0 <= selection < len(hypotheses)
        ):
            raise GenerativeForgeError("reconstrução sem lacuna precisa selecionar hipótese")
        try:
            model_task_kind = IntentTaskKind(raw["task_kind"])
            stakes = IntentStakes(raw["stakes"])
        except (TypeError, ValueError) as error:
            raise GenerativeForgeError("classificação global da intenção inválida") from error
        task_kind = task_kind_hint or model_task_kind
        overrides = (
            (f"task_kind:{model_task_kind.value}->{task_kind.value}",)
            if task_kind_hint is not None and task_kind_hint is not model_task_kind
            else ()
        )
        twin = IntentTwin(
            twin_id=f"intent-twin:{digest}",
            creation_id=creation_id,
            summary=str(raw["summary"]).strip(),
            task_kind=task_kind,
            stakes=stakes,
            observations=observations,
            hypotheses=tuple(hypotheses),
            gaps=gaps,
            selected_hypothesis_id=None if selection is None else hypotheses[selection].hypothesis_id,
        )
        return twin, model_task_kind, overrides
