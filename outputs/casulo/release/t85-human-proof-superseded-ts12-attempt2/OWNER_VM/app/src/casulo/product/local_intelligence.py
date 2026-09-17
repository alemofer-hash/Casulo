from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .platform_contracts import PlatformError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKENS = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)
MAX_MODEL_FILE_BYTES = 1024 * 1024


class LocalIntelligenceError(PlatformError):
    pass


@dataclass(frozen=True, slots=True)
class ModelCard:
    model_id: str
    artifact: Path
    sha256: str
    license_id: str
    owner: str
    redistributable: bool
    engine_role: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "artifact": str(self.artifact),
            "sha256": self.sha256,
            "license": self.license_id,
            "owner": self.owner,
            "redistributable": self.redistributable,
            "engine_role": self.engine_role,
            "kind": self.payload.get("kind"),
            "network_required": self.payload.get("network_required"),
        }


class LocalModelRegistry:
    def __init__(self, registry_path: str | Path) -> None:
        self.registry_path = Path(registry_path).expanduser().resolve(strict=True)
        self.root = self.registry_path.parent.resolve()
        if self.registry_path.is_symlink() or self.registry_path.stat().st_size > MAX_MODEL_FILE_BYTES:
            raise LocalIntelligenceError("registry inseguro ou grande demais")
        payload = _read_json(self.registry_path)
        if payload.get("schema") != "casulo-model-registry/1.0":
            raise LocalIntelligenceError("schema de model registry invalido")
        if payload.get("third_party_ai_api_required") is not False:
            raise LocalIntelligenceError("registry nao pode exigir API de terceiro")
        if payload.get("network_required_after_install") is not False:
            raise LocalIntelligenceError("registry local nao pode exigir rede")
        if payload.get("training_with_user_content") is not False:
            raise LocalIntelligenceError("treino com conteudo do usuario precisa permanecer negado")
        models = payload.get("models")
        if not isinstance(models, list) or not models:
            raise LocalIntelligenceError("registry nao contem models")
        cards: dict[str, ModelCard] = {}
        for raw in models:
            card = self._load_card(raw)
            if card.model_id in cards:
                raise LocalIntelligenceError("model_id duplicado")
            cards[card.model_id] = card
        self.cards = cards

    def require(self, model_id: str) -> ModelCard:
        try:
            return self.cards[model_id]
        except KeyError as error:
            raise LocalIntelligenceError(f"modelo local ausente: {model_id}") from error

    def report(self) -> dict[str, Any]:
        return {
            "schema": "casulo-local-intelligence/1.0",
            "models": [self.cards[key].to_dict() for key in sorted(self.cards)],
            "network_required": False,
            "third_party_ai_api_required": False,
            "training_with_user_content": False,
            "ready": {
                "guide": "casulo-guide-policy-v1" in self.cards,
                "embeddings": "casulo-exact-embedding-v1" in self.cards,
            },
        }

    def _load_card(self, raw: Any) -> ModelCard:
        if not isinstance(raw, dict):
            raise LocalIntelligenceError("model card invalido")
        required = {
            "model_id", "artifact", "sha256", "license", "owner",
            "redistributable", "engine_role",
        }
        if not required <= set(raw):
            raise LocalIntelligenceError("model card incompleto")
        artifact = (self.root / str(raw["artifact"])).resolve()
        try:
            artifact.relative_to(self.root)
        except ValueError as error:
            raise LocalIntelligenceError("artifact escapou do model registry") from error
        expected = str(raw["sha256"])
        if not _SHA256.fullmatch(expected):
            raise LocalIntelligenceError("SHA-256 do model card invalido")
        if not artifact.is_file() or artifact.is_symlink() or artifact.stat().st_size > MAX_MODEL_FILE_BYTES:
            raise LocalIntelligenceError("artifact local ausente ou inseguro")
        observed = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if observed != expected:
            raise LocalIntelligenceError("hash do modelo local diverge")
        payload = _read_json(artifact)
        if payload.get("model_id") != raw["model_id"] or payload.get("network_required") is not False:
            raise LocalIntelligenceError("identidade ou policy do modelo local diverge")
        if raw["owner"] != "Guilherme Moura Fernandes":
            raise LocalIntelligenceError("motor first-party precisa preservar ownership")
        return ModelCard(
            str(raw["model_id"]),
            artifact,
            expected,
            str(raw["license"]),
            str(raw["owner"]),
            raw["redistributable"] is True,
            str(raw["engine_role"]),
            payload,
        )


@dataclass(frozen=True, slots=True)
class ContextItem:
    context_id: str
    text: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.context_id or not self.text.strip() or not self.source_ids:
            raise LocalIntelligenceError("contexto exige identidade, texto e proveniencia")


def select_context(
    items: Iterable[ContextItem],
    *,
    mandatory_ids: frozenset[str],
    max_chars: int,
) -> tuple[ContextItem, ...]:
    materialized = tuple(items)
    by_id = {item.context_id: item for item in materialized}
    if len(by_id) != len(materialized) or mandatory_ids - set(by_id):
        raise LocalIntelligenceError("contexto obrigatorio ausente ou duplicado")
    mandatory = tuple(item for item in materialized if item.context_id in mandatory_ids)
    used = sum(len(item.text) for item in mandatory)
    if used > max_chars:
        raise LocalIntelligenceError("restricoes obrigatorias excedem budget; truncamento negado")
    selected = list(mandatory)
    for item in materialized:
        if item.context_id in mandatory_ids:
            continue
        if used + len(item.text) <= max_chars:
            selected.append(item)
            used += len(item.text)
    return tuple(selected)


class ExactEmbedding:
    def __init__(self, card: ModelCard) -> None:
        self.card = card
        self.dimensions = int(card.payload.get("dimensions", 0))
        if self.dimensions != 64 or card.payload.get("weights_required") is not False:
            raise LocalIntelligenceError("embedding first-party nao suportado")

    def embed(self, text: str) -> tuple[float, ...]:
        values = [0.0] * self.dimensions
        for token in _TOKENS.findall(text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "little") % self.dimensions
            values[index] += 1.0 if digest[2] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            values = [value / norm for value in values]
        return tuple(values)


class LocalGuidePolicy:
    def __init__(self, card: ModelCard) -> None:
        self.card = card
        self.payload = card.payload

    def respond(self, text: str, context: tuple[ContextItem, ...] = ()) -> dict[str, Any]:
        normalized = text.casefold()
        if any(marker in normalized for marker in self.payload["constraint_markers"]):
            response = self.payload["constraint_response"]
            act = "CONSTRAINT"
        elif any(marker in normalized for marker in self.payload["clarification_markers"]):
            response = self.payload["clarification_response"]
            act = "CLARIFICATION"
        else:
            response = self.payload["default_response"]
            act = "LISTENING"
        return {
            "schema": "casulo-local-guide-response/1.0",
            "act": act,
            "text": response,
            "model_id": self.card.model_id,
            "model_sha256": self.card.sha256,
            "context_ids": [item.context_id for item in context],
            "network_used": False,
            "third_party_ai_api_used": False,
        }


def load_local_intelligence(registry_path: str | Path) -> tuple[LocalModelRegistry, LocalGuidePolicy, ExactEmbedding]:
    registry = LocalModelRegistry(registry_path)
    return (
        registry,
        LocalGuidePolicy(registry.require("casulo-guide-policy-v1")),
        ExactEmbedding(registry.require("casulo-exact-embedding-v1")),
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LocalIntelligenceError(f"JSON local invalido: {path.name}") from error
    if not isinstance(payload, dict):
        raise LocalIntelligenceError("JSON local precisa ser objeto")
    return payload
