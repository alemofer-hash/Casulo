from __future__ import annotations

import html
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from .domain import DomainError, canonical_sha256
from .revolution_contracts import Requirement, RequirementGraph, RequirementStrength


INTENT_TWIN_SCHEMA = "casulo.intent-twin/1.0"


class IntentTaskKind(StrEnum):
    CONVERSATION = "CONVERSATION"
    EXPLORATION = "EXPLORATION"
    CREATION = "CREATION"


class IntentStakes(StrEnum):
    LOW = "LOW"
    MATERIAL = "MATERIAL"
    HIGH = "HIGH"


class IntentEvidenceKind(StrEnum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"


class GapStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class HypothesisImpactStatus(StrEnum):
    PRESERVES = "PRESERVES"
    CHANGES = "CHANGES"
    CONFLICTS = "CONFLICTS"
    UNKNOWN = "UNKNOWN"


def _nonempty(value: str, *, code: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError(code, f"{field_name} exige texto não vazio")
    return value.strip()


def _paths(paths: Iterable[Iterable[str]]) -> tuple[tuple[str, ...], ...]:
    normalized = tuple(tuple(part for part in path) for path in paths)
    for path in normalized:
        if not path or any(
            not isinstance(part, str)
            or not part
            or part in {".", ".."}
            or "/" in part
            or "\\" in part
            for part in path
        ):
            raise DomainError("IT100", "caminho semântico inválido")
    return normalized


@dataclass(frozen=True, slots=True)
class IntentObservation:
    observation_id: str
    statement: str
    evidence_kind: IntentEvidenceKind
    strength: RequirementStrength
    source_event_ids: tuple[str, ...]
    affected_paths: tuple[tuple[str, ...], ...]
    verifier_ids: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        _nonempty(self.observation_id, code="IT101", field_name="observation_id")
        _nonempty(self.statement, code="IT102", field_name="statement")
        if not self.source_event_ids or any(not item for item in self.source_event_ids):
            raise DomainError("IT103", "observação exige proveniência")
        object.__setattr__(self, "affected_paths", _paths(self.affected_paths))
        if not self.verifier_ids or any(not item for item in self.verifier_ids):
            raise DomainError("IT104", "observação exige verificadores futuros explícitos")
        if len(set(self.verifier_ids)) != len(self.verifier_ids):
            raise DomainError("IT105", "verificadores duplicados")
        if isinstance(self.confidence, bool) or not 0.0 <= self.confidence <= 1.0:
            raise DomainError("IT106", "confidence deve estar entre 0 e 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "statement": self.statement,
            "evidence_kind": self.evidence_kind.value,
            "strength": self.strength.value,
            "source_event_ids": list(self.source_event_ids),
            "affected_paths": [list(path) for path in self.affected_paths],
            "verifier_ids": list(self.verifier_ids),
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class HypothesisRequirementImpact:
    observation_id: str
    status: HypothesisImpactStatus
    rationale: str

    def __post_init__(self) -> None:
        _nonempty(self.observation_id, code="IT108", field_name="observation_id")
        _nonempty(self.rationale, code="IT109", field_name="impact rationale")

    def to_dict(self) -> dict[str, str]:
        return {
            "observation_id": self.observation_id,
            "status": self.status.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class IntentHypothesis:
    hypothesis_id: str
    interpretation: str
    decision_dimension: str
    choice_value: str
    excludes_choice_value: str
    consequences: tuple[str, ...]
    confidence: float
    supporting_observation_ids: tuple[str, ...]
    requirement_impacts: tuple[HypothesisRequirementImpact, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.hypothesis_id, code="IT110", field_name="hypothesis_id")
        _nonempty(self.interpretation, code="IT111", field_name="interpretation")
        _nonempty(self.decision_dimension, code="IT115", field_name="decision_dimension")
        _nonempty(self.choice_value, code="IT116", field_name="choice_value")
        _nonempty(self.excludes_choice_value, code="IT117", field_name="excludes_choice_value")
        if not self.consequences or any(not item.strip() for item in self.consequences):
            raise DomainError("IT112", "hipótese exige consequências observáveis")
        if isinstance(self.confidence, bool) or not 0.0 <= self.confidence <= 1.0:
            raise DomainError("IT113", "confidence deve estar entre 0 e 1")
        if not self.supporting_observation_ids:
            raise DomainError("IT114", "hipótese exige observações de suporte")
        impact_ids = {item.observation_id for item in self.requirement_impacts}
        if len(impact_ids) != len(self.requirement_impacts):
            raise DomainError("IT118", "impactos de hipótese duplicados")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "interpretation": self.interpretation,
            "decision_dimension": self.decision_dimension,
            "choice_value": self.choice_value,
            "excludes_choice_value": self.excludes_choice_value,
            "consequences": list(self.consequences),
            "confidence": self.confidence,
            "supporting_observation_ids": list(self.supporting_observation_ids),
            "requirement_impacts": [item.to_dict() for item in self.requirement_impacts],
        }


@dataclass(frozen=True, slots=True)
class EpistemicGap:
    gap_id: str
    question: str
    why_material: str
    affected_paths: tuple[tuple[str, ...], ...]
    information_gain: float
    source_event_ids: tuple[str, ...]
    status: GapStatus = GapStatus.OPEN
    answer: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.gap_id, code="IT120", field_name="gap_id")
        _nonempty(self.question, code="IT121", field_name="question")
        _nonempty(self.why_material, code="IT122", field_name="why_material")
        object.__setattr__(self, "affected_paths", _paths(self.affected_paths))
        if isinstance(self.information_gain, bool) or not 0.0 <= self.information_gain <= 1.0:
            raise DomainError("IT123", "information_gain deve estar entre 0 e 1")
        if not self.source_event_ids:
            raise DomainError("IT124", "lacuna exige proveniência")
        if self.status is GapStatus.RESOLVED and not (self.answer and self.answer.strip()):
            raise DomainError("IT125", "lacuna resolvida exige resposta")
        if self.status is GapStatus.OPEN and self.answer is not None:
            raise DomainError("IT126", "lacuna aberta não pode conter resposta")

    def resolve(self, answer: str, *, source_event_id: str) -> "EpistemicGap":
        if self.status is not GapStatus.OPEN:
            raise DomainError("IT127", "lacuna já foi resolvida")
        clean = _nonempty(answer, code="IT128", field_name="answer")
        return replace(
            self,
            status=GapStatus.RESOLVED,
            answer=clean,
            source_event_ids=(*self.source_event_ids, source_event_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "question": self.question,
            "why_material": self.why_material,
            "affected_paths": [list(path) for path in self.affected_paths],
            "information_gain": self.information_gain,
            "source_event_ids": list(self.source_event_ids),
            "status": self.status.value,
            "answer": self.answer,
        }


@dataclass(frozen=True, slots=True)
class IntentTwin:
    twin_id: str
    creation_id: str
    summary: str
    task_kind: IntentTaskKind
    stakes: IntentStakes
    observations: tuple[IntentObservation, ...]
    hypotheses: tuple[IntentHypothesis, ...]
    gaps: tuple[EpistemicGap, ...]
    selected_hypothesis_id: str | None = None
    confirmation_event_ids: tuple[str, ...] = ()
    schema: str = INTENT_TWIN_SCHEMA

    def __post_init__(self) -> None:
        _nonempty(self.twin_id, code="IT130", field_name="twin_id")
        _nonempty(self.creation_id, code="IT131", field_name="creation_id")
        _nonempty(self.summary, code="IT132", field_name="summary")
        if not self.observations:
            raise DomainError("IT133", "IntentTwin exige ao menos uma observação")
        observation_ids = {item.observation_id for item in self.observations}
        if len(observation_ids) != len(self.observations):
            raise DomainError("IT134", "observações duplicadas")
        hypothesis_ids = {item.hypothesis_id for item in self.hypotheses}
        if not hypothesis_ids or len(hypothesis_ids) != len(self.hypotheses):
            raise DomainError("IT135", "hipóteses precisam ser únicas")
        dimensions = {item.decision_dimension.strip().casefold() for item in self.hypotheses}
        choices = {item.choice_value.strip().casefold() for item in self.hypotheses}
        if len(self.hypotheses) > 1 and len(choices) != len(self.hypotheses):
            raise DomainError("IT149", "hipóteses precisam divergir por uma escolha material")
        if len(self.hypotheses) > 1 and len(dimensions) != 1:
            raise DomainError("IT151", "hipóteses precisam disputar a mesma dimensão de decisão")
        if len(self.hypotheses) == 2:
            first, second = self.hypotheses
            if (
                first.excludes_choice_value.strip().casefold() != second.choice_value.strip().casefold()
                or second.excludes_choice_value.strip().casefold() != first.choice_value.strip().casefold()
            ):
                raise DomainError("IT152", "hipóteses precisam declarar exclusão mútua verificável")
        for hypothesis in self.hypotheses:
            if not set(hypothesis.supporting_observation_ids).issubset(observation_ids):
                raise DomainError("IT136", "hipótese referencia observação desconhecida")
            impact_ids = {item.observation_id for item in hypothesis.requirement_impacts}
            if impact_ids != observation_ids:
                raise DomainError("IT153", "hipótese precisa classificar todas as observações")
        gap_ids = {item.gap_id for item in self.gaps}
        if len(gap_ids) != len(self.gaps):
            raise DomainError("IT137", "lacunas duplicadas")
        if set(self.viable_hypothesis_ids) != hypothesis_ids:
            raise DomainError("IT156", "candidato contém hipótese incompatível com requisito HARD")
        if self.selected_hypothesis_id is not None:
            if self.selected_hypothesis_id not in hypothesis_ids:
                raise DomainError("IT138", "hipótese selecionada é desconhecida")
            if self.selected_hypothesis_id not in self.viable_hypothesis_ids:
                raise DomainError("IT154", "hipótese selecionada conflita com requisito HARD")
        if self.confirmation_event_ids and not self.production_ready:
            raise DomainError("IT139", "confirmação não pode contornar lacunas ou seleção")

    @property
    def open_gaps(self) -> tuple[EpistemicGap, ...]:
        return tuple(item for item in self.gaps if item.status is GapStatus.OPEN)

    @property
    def confirmed(self) -> bool:
        return bool(self.confirmation_event_ids)

    @property
    def viable_hypothesis_ids(self) -> tuple[str, ...]:
        hard_ids = {
            item.observation_id
            for item in self.observations
            if item.strength is RequirementStrength.HARD
        }
        return tuple(
            hypothesis.hypothesis_id
            for hypothesis in self.hypotheses
            if all(
                impact.status is HypothesisImpactStatus.PRESERVES
                for impact in hypothesis.requirement_impacts
                if impact.observation_id in hard_ids
            )
        )

    @property
    def production_ready(self) -> bool:
        return (
            self.task_kind is IntentTaskKind.CREATION
            and not self.open_gaps
            and self.selected_hypothesis_id is not None
        )

    def resolve_gap(
        self,
        gap_id: str,
        answer: str,
        *,
        source_event_id: str,
        selected_hypothesis_id: str | None = None,
        refined_summary: str | None = None,
        additional_observations: tuple[IntentObservation, ...] = (),
        updated_hypotheses: tuple[IntentHypothesis, ...] | None = None,
    ) -> "IntentTwin":
        if self.confirmed:
            raise DomainError("IT140", "IntentTwin confirmado é imutável")
        found = False
        gaps: list[EpistemicGap] = []
        for gap in self.gaps:
            if gap.gap_id == gap_id:
                found = True
                gaps.append(gap.resolve(answer, source_event_id=source_event_id))
            else:
                gaps.append(gap)
        if not found:
            raise DomainError("IT141", "lacuna desconhecida")
        return replace(
            self,
            summary=(refined_summary or self.summary).strip(),
            observations=(*self.observations, *additional_observations),
            hypotheses=updated_hypotheses or self.hypotheses,
            gaps=tuple(gaps),
            selected_hypothesis_id=selected_hypothesis_id or self.selected_hypothesis_id,
        )

    def select(self, hypothesis_id: str) -> "IntentTwin":
        if self.confirmed:
            raise DomainError("IT142", "IntentTwin confirmado é imutável")
        if hypothesis_id not in {item.hypothesis_id for item in self.hypotheses}:
            raise DomainError("IT143", "hipótese selecionada é desconhecida")
        if hypothesis_id not in self.viable_hypothesis_ids:
            raise DomainError("IT155", "hipótese não preserva todos os requisitos HARD")
        return replace(self, selected_hypothesis_id=hypothesis_id)

    def confirm(self, *, human_event_id: str, explicit_human_approval: bool) -> "IntentTwin":
        if not explicit_human_approval or not human_event_id.startswith("human:"):
            raise DomainError("IT144", "somente confirmação humana explícita é válida")
        if not self.production_ready:
            raise DomainError("IT145", "IntentTwin ainda possui incerteza material")
        confirmed_observations = tuple(
            replace(item, evidence_kind=IntentEvidenceKind.CONFIRMED)
            if item.evidence_kind is IntentEvidenceKind.INFERRED
            else item
            for item in self.observations
        )
        return replace(
            self,
            observations=confirmed_observations,
            confirmation_event_ids=(*self.confirmation_event_ids, human_event_id),
        )

    def requirement_graph(self) -> RequirementGraph:
        if not self.confirmed:
            raise DomainError("IT146", "RequirementGraph exige IntentTwin confirmado")
        eligible = tuple(
            item
            for item in self.observations
            if item.evidence_kind in {IntentEvidenceKind.EXPLICIT, IntentEvidenceKind.CONFIRMED}
        )
        requirements = tuple(
            Requirement(
                requirement_id=f"req:{self.twin_id}:{item.observation_id}",
                statement=item.statement,
                strength=item.strength,
                weight=2.0 if item.strength is RequirementStrength.HARD else 1.0,
                source_event_ids=tuple(dict.fromkeys((*item.source_event_ids, *self.confirmation_event_ids))),
                verifier_ids=item.verifier_ids,
                scope=".".join(item.affected_paths[0]),
            )
            for item in eligible
        )
        if not any(item.strength is RequirementStrength.HARD for item in requirements):
            raise DomainError("IT147", "produção exige ao menos um requisito HARD")
        return RequirementGraph(requirements)

    def production_brief(self) -> str:
        if not self.confirmed:
            raise DomainError("IT148", "brief de produção exige confirmação")
        selected = next(item for item in self.hypotheses if item.hypothesis_id == self.selected_hypothesis_id)
        requirements = [
            f"[{item.strength.value}] {item.statement}"
            for item in self.observations
            if item.evidence_kind in {IntentEvidenceKind.EXPLICIT, IntentEvidenceKind.CONFIRMED}
        ]
        return "\n".join(
            (
                f"Finalidade confirmada: {self.summary}",
                f"Interpretação escolhida: {selected.interpretation}",
                f"Decisão material: {selected.decision_dimension} = {selected.choice_value}",
                "Requisitos observáveis:",
                *(f"- {item}" for item in requirements),
                "Não trate hipótese não selecionada como requisito.",
            )
        )

    def to_dict(self) -> dict[str, Any]:
        document = {
            "schema": self.schema,
            "twin_id": self.twin_id,
            "creation_id": self.creation_id,
            "summary": self.summary,
            "task_kind": self.task_kind.value,
            "stakes": self.stakes.value,
            "observations": [item.to_dict() for item in self.observations],
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "gaps": [item.to_dict() for item in self.gaps],
            "selected_hypothesis_id": self.selected_hypothesis_id,
            "confirmation_event_ids": list(self.confirmation_event_ids),
        }
        return {**document, "canonical_sha256": canonical_sha256(document)}


class IntentTwinRenderer:
    """Total renderer over the validated domain type; raw model dictionaries are refused."""

    @staticmethod
    def render(twin: IntentTwin, destination: Path) -> Path:
        if not isinstance(twin, IntentTwin):
            raise DomainError("IT150", "renderer aceita somente IntentTwin validado")
        destination.mkdir(parents=True, exist_ok=False)
        chosen = twin.selected_hypothesis_id or "ainda não escolhida"
        observations = "".join(
            f"<li><b>{html.escape(item.evidence_kind.value)}</b> · "
            f"{html.escape(item.strength.value)} · {html.escape(item.statement)}</li>"
            for item in twin.observations
        )
        hypotheses = "".join(
            f"<article class='hypothesis{' selected' if item.hypothesis_id == twin.selected_hypothesis_id else ''}'>"
            f"<small>{html.escape(item.hypothesis_id)} · {item.confidence:.0%}</small>"
            f"<p>{html.escape(item.interpretation)}</p>"
            f"<p><b>Decisão material:</b> {html.escape(item.decision_dimension)} = {html.escape(item.choice_value)}"
            f" <small>(exclui {html.escape(item.excludes_choice_value)})</small></p>"
            f"<ul>{''.join(f'<li>{html.escape(impact.status.value)} · {html.escape(impact.rationale)}</li>' for impact in item.requirement_impacts)}</ul>"
            f"<ul>{''.join(f'<li>{html.escape(value)}</li>' for value in item.consequences)}</ul></article>"
            for item in twin.hypotheses
        )
        gaps = "".join(
            f"<li class='{html.escape(item.status.value.lower())}'><b>{html.escape(item.status.value)}</b> · "
            f"{html.escape(item.question)}<br><small>{html.escape(item.why_material)}</small></li>"
            for item in twin.gaps
        ) or "<li>Nenhuma lacuna material aberta.</li>"
        page = f"""<!doctype html>
<html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>Casulo · IntentTwin</title><style>
:root{{--ink:#eef4ff;--muted:#9ba9bd;--bg:#071018;--panel:#101d28;--amber:#f2b65d;--blue:#55a9d6}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 50% 5%,#153248,var(--bg) 52%);color:var(--ink);font:16px/1.55 system-ui;padding:5vw}}
main{{max-width:960px;margin:auto}}h1{{font-size:clamp(2rem,6vw,4.6rem);margin:.1em 0}}h2{{color:var(--amber)}}small,.muted{{color:var(--muted)}}section{{background:#101d28dd;border:1px solid #294156;border-radius:22px;padding:1.2rem;margin:1rem 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}}.hypothesis{{border-left:3px solid var(--blue);padding:.7rem 1rem;background:#0a151e}}.selected{{border-color:var(--amber)}}.open{{color:#ffd29a}}code{{color:var(--blue)}}</style></head>
<body><main><p class='muted'>Casulo · reconstrução verificável da intenção</p><h1>{html.escape(twin.summary)}</h1>
<p><code>{html.escape(twin.creation_id)}</code> · {html.escape(twin.task_kind.value)} · risco {html.escape(twin.stakes.value)}</p>
<section><h2>O que foi observado</h2><ul>{observations}</ul></section>
<section><h2>Interpretações possíveis</h2><div class='grid'>{hypotheses}</div><p>Escolhida: <b>{html.escape(chosen)}</b></p></section>
<section><h2>O que ainda falta saber</h2><ul>{gaps}</ul></section>
<p class='muted'>Produção liberada: {'sim' if twin.confirmed else 'não'} · hash {html.escape(twin.to_dict()['canonical_sha256'])}</p>
</main></body></html>"""
        index = destination / "index.html"
        index.write_text(page, encoding="utf-8", newline="\n")
        return index
