from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

from .domain import canonical_sha256
from .intent_reconstruction import IntentEvidenceKind, IntentTwin
from .platform_contracts import PlatformError, Storage
from .revolution_contracts import RequirementStrength


CREATIVE_INTERLOCUTION_SCHEMA = "casulo.creative-interlocution/1.0"
GUIDE_IDENTITY_SCHEMA = "casulo.guide-identity/1.0"
_IDENTITY_PATH = "identity/guide.json"
_GUIDE_NAME = re.compile(r"^[A-Za-z0-9À-ÖØ-öø-ÿ][A-Za-z0-9À-ÖØ-öø-ÿ _-]{0,31}$")
_IMPLEMENTATION_TERMS = (
    "algoritmo",
    "api",
    "arquitetura",
    "backend",
    "banco de dados",
    "biblioteca",
    "cache",
    "cloud",
    "compilador",
    "cpu",
    "dataset",
    "endpoint",
    "framework",
    "frontend",
    "gpu",
    "hash",
    "hiperparâmetro",
    "infraestrutura",
    "json",
    "kernel",
    "linguagem de programação",
    "matriz",
    "modelo de dados",
    "parâmetro técnico",
    "precisão numérica",
    "protocolo",
    "runtime",
    "schema",
    "servidor",
    "sql",
    "tensor",
    "thread",
)
_ENGINEERING_PROGRESS = {
    "Workspace isolado e contrato inicial preservados.":
        "Guardei sua ideia e preparei um espaço seguro para ela.",
    "IntentDelta real gerado e persistido.":
        "A primeira forma interna da criação foi registrada.",
    "RequirementGraph compilado para fatos T, ainda sem claim de aceite.":
        "Organizei o que a criação precisa cumprir sem fingir que já está pronto.",
    "Projeto T candidato gerado e selado para verificação.":
        "Transformei o que entendi em uma construção que já pode ser conferida.",
    "T compilado e diagnostics reais convergiram dentro do budget.":
        "A estrutura principal fechou; as correções necessárias foram incorporadas.",
    "Simulação concluída sem efeitos reais.":
        "Experimentei a criação num ambiente seguro, sem mexer no mundo real.",
    "Pacote Casulo materializado e selado.":
        "A criação virou um pacote preservado e pronto para sair do Casulo.",
    "Execução externa e round-trip concluídos.":
        "Abri a criação fora daqui e confirmei que ela consegue voltar para ser editada.",
}


def _contains_term(text: str, term: str) -> bool:
    folded = text.casefold()
    if " " in term:
        return term in folded
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", folded) is not None


def validate_experiential_question(question: str) -> str:
    """Keep implementation choices inside Casulo instead of handing them to the user."""

    cleaned = " ".join(question.split())
    if not cleaned:
        raise PlatformError("pergunta de criação vazia")
    exposed = tuple(term for term in _IMPLEMENTATION_TERMS if _contains_term(cleaned, term))
    if exposed:
        raise PlatformError(
            "pergunta transfere decisão técnica ao usuário: " + ", ".join(exposed)
        )
    return cleaned


def humanize_engineering_progress(summary: str) -> str:
    """Project a real engineering milestone without exposing machinery in the main flow."""

    cleaned = " ".join(summary.split())
    if not cleaned:
        raise PlatformError("marco de criação vazio")
    return _ENGINEERING_PROGRESS.get(cleaned, cleaned)


@dataclass(frozen=True, slots=True)
class GuideIdentity:
    name: str
    chosen_by_user: bool
    source_event_ids: tuple[str, ...]
    schema: str = GUIDE_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        normalized = " ".join(self.name.split())
        if not _GUIDE_NAME.fullmatch(normalized):
            raise PlatformError(
                "nome do Guia aceita 1–32 letras, números, espaço, hífen ou sublinhado"
            )
        if not self.source_event_ids:
            raise PlatformError("identidade do Guia exige proveniência")
        object.__setattr__(self, "name", normalized)

    @classmethod
    def default(cls) -> "GuideIdentity":
        return cls("Casulo", False, ("system:default-guide-identity",))

    def renamed(
        self,
        name: str,
        *,
        human_event_id: str,
        explicit_human_choice: bool,
    ) -> "GuideIdentity":
        if not explicit_human_choice or not human_event_id.startswith("human:"):
            raise PlatformError("nome do Guia exige escolha humana explícita")
        return replace(
            self,
            name=name,
            chosen_by_user=True,
            source_event_ids=(*self.source_event_ids, human_event_id),
        )

    def to_dict(self) -> dict[str, Any]:
        document = {
            "schema": self.schema,
            "name": self.name,
            "chosen_by_user": self.chosen_by_user,
            "source_event_ids": list(self.source_event_ids),
        }
        return {**document, "canonical_sha256": canonical_sha256(document)}

    @classmethod
    def from_dict(cls, value: Any) -> "GuideIdentity":
        if not isinstance(value, dict):
            raise PlatformError("identidade persistida do Guia precisa ser objeto")
        expected = {"schema", "name", "chosen_by_user", "source_event_ids", "canonical_sha256"}
        if set(value) != expected or value.get("schema") != GUIDE_IDENTITY_SCHEMA:
            raise PlatformError("schema da identidade do Guia é incompatível")
        document = {key: value[key] for key in expected - {"canonical_sha256"}}
        if value["canonical_sha256"] != canonical_sha256(document):
            raise PlatformError("identidade do Guia foi adulterada")
        chosen = value["chosen_by_user"]
        sources = value["source_event_ids"]
        if not isinstance(chosen, bool) or not isinstance(sources, list):
            raise PlatformError("identidade persistida do Guia é inválida")
        return cls(str(value["name"]), chosen, tuple(str(item) for item in sources))


class GuideIdentityStore:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def load(self) -> GuideIdentity:
        try:
            payload = self.storage.read(_IDENTITY_PATH)
        except FileNotFoundError:
            return GuideIdentity.default()
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PlatformError("identidade persistida do Guia não é JSON UTF-8 válido") from error
        return GuideIdentity.from_dict(value)

    def save(self, identity: GuideIdentity) -> None:
        payload = json.dumps(
            identity.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        self.storage.write_atomic(_IDENTITY_PATH, payload)


@dataclass(frozen=True, slots=True)
class CreativeIntentProjection:
    creation_id: str
    summary: str
    visible_question: str | None
    requirement_count: int
    hard_requirement_count: int
    explicit_count: int
    inferred_count: int
    source_event_ids: tuple[str, ...]
    engineering_details_visible: bool = False
    schema: str = CREATIVE_INTERLOCUTION_SCHEMA

    @classmethod
    def from_twin(cls, twin: IntentTwin) -> "CreativeIntentProjection":
        question = None
        if twin.open_gaps:
            if len(twin.open_gaps) != 1:
                raise PlatformError("interlocução criativa aceita no máximo uma escolha material")
            question = validate_experiential_question(twin.open_gaps[0].question)
        sources = tuple(
            dict.fromkeys(
                source
                for observation in twin.observations
                for source in observation.source_event_ids
            )
        )
        return cls(
            creation_id=twin.creation_id,
            summary=twin.summary,
            visible_question=question,
            requirement_count=len(twin.observations),
            hard_requirement_count=sum(
                item.strength is RequirementStrength.HARD for item in twin.observations
            ),
            explicit_count=sum(
                item.evidence_kind is IntentEvidenceKind.EXPLICIT for item in twin.observations
            ),
            inferred_count=sum(
                item.evidence_kind is IntentEvidenceKind.INFERRED for item in twin.observations
            ),
            source_event_ids=sources,
        )

    def visible_text(self, guide_name: str) -> str:
        identity = GuideIdentity(guide_name, False, ("system:visible-projection",))
        return f"{identity.name} entendeu assim: {self.summary}"

    def to_dict(self) -> dict[str, Any]:
        document = {
            "schema": self.schema,
            "creation_id": self.creation_id,
            "summary": self.summary,
            "visible_question": self.visible_question,
            "requirement_count": self.requirement_count,
            "hard_requirement_count": self.hard_requirement_count,
            "explicit_count": self.explicit_count,
            "inferred_count": self.inferred_count,
            "source_event_ids": list(self.source_event_ids),
            "engineering_details_visible": self.engineering_details_visible,
        }
        return {**document, "canonical_sha256": canonical_sha256(document)}
