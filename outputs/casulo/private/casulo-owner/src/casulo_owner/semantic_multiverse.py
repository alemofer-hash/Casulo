from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from casulo.product.neural_budget import NeuralOperation, NeuralRouteDecision
from casulo.product.semantic_multiverse import (
    ActivationProfile,
    CancellationToken,
    ContentAddressedUniverseStore,
    GlobalSemanticCatalog,
    MemoryThermostat,
    OperationalEquivalenceHarness,
    SemanticTransitionRuntime,
    SemanticUniverseManifest,
    SufficientProjection,
    UniverseLifecycleManager,
    canonical_json,
    sha256_bytes,
    sha256_json,
)
from casulo.t.semantic_ir import SemanticLowerer, build_semantic_tcap

from .local_model_runtime import (
    ChatMessage,
    GenerationRequest,
    LocalModelRuntime,
    ModelStreamKind,
    StochasticTrace,
    initial_sampling_policies,
)
from .neural_budgeting import budgeted_policy, validate_budgeted_messages


REQUIRED_STATE_FIELDS = ("intent", "constraints", "units", "uncertainty", "provenance")
UNIVERSE_ORDER = ("intencao", "sinais", "engenharia", "diagnostico", "interface", "materializacao")


@dataclass(frozen=True, slots=True)
class GenerativeRouteProposal:
    operation_id: str
    route: tuple[str, ...]
    rationale: str
    trace: StochasticTrace
    raw_sha256: str
    route_decision: NeuralRouteDecision | None = None


class GenerativeUniversePlanner:
    """Neural proposal boundary; policy and execution remain deterministic."""

    def __init__(self, runtime: LocalModelRuntime) -> None:
        self.runtime = runtime

    def propose(self, idea: str, *, operation_id: str, cancellation: Any) -> GenerativeRouteProposal:
        route_decision, policy = budgeted_policy(
            NeuralOperation.SEMANTIC_ROUTING,
            source_event_ids=(f"operation:{operation_id}",),
        )
        schema = {
            "type": "object",
            "properties": {
                "route": {"type": "array", "items": {"type": "string", "enum": list(UNIVERSE_ORDER)}, "minItems": 3, "maxItems": 6},
                "rationale": {"type": "string", "minLength": 12, "maxLength": 500},
            },
            "required": ["route", "rationale"],
            "additionalProperties": False,
        }
        messages = (
            ChatMessage("system", "Você propõe uma rota entre universos semânticos. Não concede capabilities. Selecione 3 a 6 universos distintos necessários e responda apenas JSON válido."),
            ChatMessage("user", f"Ideia em pt-BR: {idea}\nUniversos permitidos: {', '.join(UNIVERSE_ORDER)}"),
        )
        validate_budgeted_messages(route_decision, messages)
        request = GenerationRequest(
            operation_id,
            messages,
            policy,
            schema,
        )
        chunks: list[str] = []
        trace: StochasticTrace | None = None
        for event in self.runtime.stream_chat(request, cancellation):
            if event.kind is ModelStreamKind.TOKEN:
                chunks.append(event.content)
            elif event.kind is ModelStreamKind.COMPLETED:
                trace = event.trace
        raw = "".join(chunks).strip()
        if trace is None or not raw:
            raise RuntimeError("proposta neural de rota não foi concluída")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError("proposta neural de rota não é JSON válido") from error
        if not isinstance(payload, dict) or set(payload) != {"route", "rationale"}:
            raise RuntimeError("proposta neural de rota diverge do schema")
        route = tuple(payload["route"]) if isinstance(payload["route"], list) else ()
        if not 3 <= len(route) <= 6 or len(set(route)) != len(route) or set(route) - set(UNIVERSE_ORDER):
            raise RuntimeError("proposta neural não possui três universos distintos permitidos")
        rationale = str(payload["rationale"]).strip()
        if not 12 <= len(rationale) <= 500:
            raise RuntimeError("rationale neural fora dos limites")
        return GenerativeRouteProposal(
            operation_id,
            route,
            rationale,
            trace,
            sha256_bytes(raw.encode("utf-8")),
            route_decision,
        )


def first_party_universe_manifests(store: ContentAddressedUniverseStore) -> tuple[SemanticUniverseManifest, ...]:
    descriptions = {
        "intencao": "preserva finalidade, decisões e constraints confirmadas",
        "sinais": "interpreta sinais e séries sem autorizar dispositivos",
        "engenharia": "estrutura hipóteses e cálculos de engenharia",
        "diagnostico": "compara hipóteses, incerteza e evidência",
        "interface": "projeta interação e estados observáveis",
        "materializacao": "compila T, simula e empacota sob gates",
    }
    manifests: list[SemanticUniverseManifest] = []
    for index, universe_id in enumerate(UNIVERSE_ORDER):
        blob = canonical_json({"schema": "casulo.first-party-universe-base/1.0", "universe_id": universe_id, "description": descriptions[universe_id]})
        digest, _ = store.publish_blob(blob)
        neighbors = tuple(item for item in UNIVERSE_ORDER if item != universe_id)
        manifest = SemanticUniverseManifest(
            universe_id=universe_id, version=1, content_hash=digest, parent_hashes=(),
            semantic_address=tuple(dict.fromkeys((universe_id, *_tokens(descriptions[universe_id])))),
            invariants=REQUIRED_STATE_FIELDS, variants_schema={"confirmed_delta": "casulo.universe-delta/1.0"},
            input_contracts=("SufficientStateV1",), output_contracts=("SufficientStateV1",),
            capabilities=("model.infer",), neighbors=neighbors,
            activation_profile=ActivationProfile((12 + index) * 1024 * 1024, 3 + index, 512 * 1024),
            resolution_levels=("identity", "working", "detailed"), license="PRIVATE_FIRST_PARTY",
            provenance=("Teloscorp", "Guilherme Moura Fernandes", "semantic-multiverse-goal-2026-08-12"),
            signature=None, migration_policy="explicit-versioned-only",
        )
        store.publish_manifest(manifest)
        manifests.append(manifest)
    return tuple(manifests)


class OwnerSemanticMultiverse:
    def __init__(self, root: Path, *, hot_limit: int = 3, memory_limit_bytes: int = 48 * 1024 * 1024) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = ContentAddressedUniverseStore(self.root / "store")
        self.manifests = first_party_universe_manifests(self.store)
        self.by_id = {item.universe_id: item for item in self.manifests}
        self.catalog = GlobalSemanticCatalog()
        self.catalog.rebuild(self.manifests)
        self.lifecycle = UniverseLifecycleManager(self.manifests, hot_limit=hot_limit, memory_limit_bytes=memory_limit_bytes)
        self.thermostat = MemoryThermostat(self.lifecycle)
        self.transitions = SemanticTransitionRuntime()
        self.physical_runtime: Any | None = None
        self._last_physical_state: dict[str, Any] | None = None

    def attach_physical_runtime(self, runtime: Any) -> None:
        if set(runtime.store.catalog) != set(self.by_id):
            raise RuntimeError("catálogo físico diverge do catálogo semântico")
        if any(state != "FROZEN" for state in runtime.store.states.values()):
            raise RuntimeError("runtime físico precisa iniciar FROZEN")
        self.physical_runtime = runtime

    def execute(self, proposal: GenerativeRouteProposal, *, idea: str, constraints: tuple[str, ...], confirmed: bool, cancellation: CancellationToken, confirmation_source: str = "HUMAN_EXPLICIT") -> dict[str, Any]:
        if not confirmed:
            raise RuntimeError("rota material não confirmada")
        if confirmation_source not in {"HUMAN_EXPLICIT", "AUTOMATED_ACCEPTANCE_SCENARIO"}:
            raise RuntimeError("origem de confirmação inválida")
        route = proposal.route
        if not 3 <= len(route) <= len(UNIVERSE_ORDER) or len(set(route)) != len(route):
            raise RuntimeError("rota generativa inválida")
        state: dict[str, Any] = {
            "intent": idea,
            "constraints": list(constraints),
            "units": "SI",
            "uncertainty": "explicit",
            "provenance": [proposal.operation_id, proposal.trace.output_sha256],
            "route_rationale": proposal.rationale,
        }
        lifecycle_receipts: list[dict[str, Any]] = []
        transition_receipts: list[dict[str, Any]] = []
        physical_receipts: list[dict[str, Any]] = []
        visited: list[str] = []
        for index, universe_id in enumerate(route):
            cancellation.checkpoint()
            if self.physical_runtime is not None:
                for physical in self.physical_runtime.reconcile(
                    (universe_id,), allowed_capabilities=frozenset({"model.infer"}),
                    sufficient_state=state, constraints=state["constraints"], provenance=state["provenance"],
                ):
                    physical_receipts.append(_enum_dict(physical))
            for receipt in self.lifecycle.activate(universe_id, cancellation, reason="generative-route"):
                lifecycle_receipts.append(_enum_dict(receipt))
            self.lifecycle.acquire(universe_id)
            visited.append(universe_id)
            if index:
                source, destination = self.by_id[route[index - 1]], self.by_id[universe_id]
                projected, receipt = self.transitions.execute(
                    transition_id=f"{source.universe_id}-{destination.universe_id}-v1",
                    source=source, destination=destination, state=state,
                    projection=SufficientProjection(f"sufficient-{source.universe_id}-{destination.universe_id}", REQUIRED_STATE_FIELDS),
                    required_invariants=REQUIRED_STATE_FIELDS,
                    allowed_capabilities=frozenset({"model.infer"}),
                    provenance_root=sha256_json(state["provenance"]), token=cancellation,
                    uncertainty=0.1,
                )
                transition_receipts.append(_enum_dict(receipt))
                state = {**projected, "provenance": [*projected["provenance"], receipt.output_hash]}
            self.lifecycle.release(universe_id)
        for receipt in self.thermostat.reconcile((route[-1],), cancellation):
            lifecycle_receipts.append(_enum_dict(receipt))
        delta_hash = self.store.publish_delta(base_hash=self.by_id[route[-1]].content_hash, delta={"idea_hash": sha256_bytes(idea.encode("utf-8")), "route": list(route), "transition_receipts": [item["output_hash"] for item in transition_receipts]}, confirmed=True)
        semantic_manifests = [self._semantic_manifest(item) for item in route]
        semantic_transitions = [self._semantic_transition(route[index], route[index + 1]) for index in range(len(route) - 1)]
        semantic_ir = SemanticLowerer().lower(semantic_manifests, semantic_transitions)
        semantic_tcap = build_semantic_tcap(semantic_ir)
        semantic_tcap_hash, semantic_tcap_deduplicated = self.store.publish_blob(semantic_tcap)
        result = {
            "schema": "casulo.owner-semantic-multiverse-session/1.0",
            "operation_id": proposal.operation_id,
            "confirmation_source": confirmation_source,
            "idea_sha256": sha256_bytes(idea.encode("utf-8")),
            "proposal": {"route": list(route), "rationale": proposal.rationale, "trace": proposal.trace.to_dict(), "raw_sha256": proposal.raw_sha256},
            "universes_installed": len(self.manifests), "universes_visited": visited,
            "hot_at_completion": list(self.lifecycle.hot), "strict_hot_subset": 0 < len(self.lifecycle.hot) < len(self.manifests),
            "lifecycle_receipts": lifecycle_receipts, "transition_receipts": transition_receipts,
            "physical_lifecycle_receipts": physical_receipts,
            "final_state": state, "confirmed_delta_hash": delta_hash,
            "semantic_ir_sha256": semantic_ir.sha256, "semantic_tcap_sha256": semantic_tcap_hash,
            "semantic_tcap_deduplicated": semantic_tcap_deduplicated,
            "cloud": "RELEASE_LOCKED", "network": "DENIED", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY",
        }
        self._last_physical_state = dict(state)
        self._persist(result)
        return result

    def shutdown_physical(self) -> None:
        if self.physical_runtime is None:
            return
        state = self._last_physical_state or {
            "intent": "safe shutdown", "constraints": ["sem rede"], "units": "SI",
            "uncertainty": "explicit", "provenance": ["owner:shutdown"],
        }
        for universe_id, status in tuple(self.physical_runtime.store.states.items()):
            if status != "HOT":
                continue
            since = self.physical_runtime.hot_since.get(universe_id, self.physical_runtime.clock_ns())
            remaining = self.physical_runtime.minimum_residence_ns - (self.physical_runtime.clock_ns() - since)
            if remaining > 0:
                time.sleep(remaining / 1_000_000_000)
            self.physical_runtime.hibernate(
                universe_id, sufficient_state=state, constraints=state["constraints"],
                provenance=state["provenance"],
            )
        self.physical_runtime.close()

    def reboot(self) -> dict[str, Any]:
        self.shutdown_physical()
        self.lifecycle.restore_cold()
        sessions = sorted((self.root / "sessions").glob("*.json")) if (self.root / "sessions").exists() else []
        return {"catalog_sha256": self.catalog.snapshot.sha256, "sessions": len(sessions), "restored_session_hashes": [sha256_bytes(path.read_bytes()) for path in sessions], "hot_after_reboot": list(self.lifecycle.hot), "false_hot_persistence": False}

    def inspect(self) -> dict[str, Any]:
        result = {"catalog_version": self.catalog.snapshot.version, "catalog_sha256": self.catalog.snapshot.sha256, "states": {key: value.value for key, value in sorted(self.lifecycle.states.items())}, "hot": list(self.lifecycle.hot), "hot_memory_bytes": self.lifecycle.hot_memory_bytes, "receipts": len(self.lifecycle.receipts)}
        if self.physical_runtime is not None:
            observed = self.physical_runtime.store.observe()
            result["physical"] = {
                "states": dict(sorted(self.physical_runtime.store.states.items())),
                "mapped_bytes": observed.mapped_bytes, "cache_bytes": observed.cache_bytes,
                "rss_bytes": observed.rss_bytes, "private_working_set_bytes": observed.private_working_set_bytes,
                "t_receipts": self.physical_runtime.sequence,
                "foreign_receipts": len(self.physical_runtime.foreign_receipts),
            }
        return result

    def gc_plan(self) -> dict[str, Any]:
        protected = {item.content_hash for item in self.manifests}
        sessions = self.root / "sessions"
        if sessions.exists():
            for path in sessions.glob("*.json"):
                try:
                    protected.add(str(json.loads(path.read_text(encoding="utf-8"))["semantic_tcap_sha256"]))
                except (OSError, UnicodeError, json.JSONDecodeError, KeyError):
                    continue
        return self.store.gc_plan(protected)

    def render(self, session: Mapping[str, Any], destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        events = []
        for receipt in session["lifecycle_receipts"]:
            events.append(f"<li><b>{html.escape(receipt['universe_id'])}</b>: {html.escape(receipt['before'])} → {html.escape(receipt['after'])}</li>")
        for receipt in session["transition_receipts"]:
            events.append(f"<li><b>{html.escape(receipt['source'])} → {html.escape(receipt['destination'])}</b>: {receipt['bytes_read']} B → {receipt['bytes_transferred']} B</li>")
        path = destination / "index.html"
        path.write_text("<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>Casulo Semantic Multiverse</title><style>body{background:#07101d;color:#f5f0df;font:16px system-ui;padding:48px;max-width:960px;margin:auto}h1{font-weight:400}.hot{color:#e5a33b}.locked{color:#7ea7d8}li{margin:10px 0}</style><p>TELOSCORP · CASULO</p><h1>Semantic Multiverse</h1><p class='hot'>HOT: " + html.escape(", ".join(session["hot_at_completion"])) + "</p><p class='locked'>Cloud locked · rede negada · USB proibido</p><ol>" + "".join(events) + "</ol><p>Visual provisório derivado apenas de receipts reais.</p></html>", encoding="utf-8", newline="\n")
        return path

    def _persist(self, result: Mapping[str, Any]) -> None:
        sessions = self.root / "sessions"
        sessions.mkdir(exist_ok=True)
        identity = sha256_json(result)
        (sessions / f"{identity}.json").write_bytes(canonical_json(dict(result)) + b"\n")

    def _semantic_manifest(self, universe_id: str) -> dict[str, Any]:
        item = self.by_id[universe_id]
        return {"universe_id": item.universe_id, "version": item.version, "content_hash": item.content_hash, "semantic_address": list(item.semantic_address), "invariants": list(item.invariants), "capabilities": list(item.capabilities), "neighbors": list(item.neighbors), "resolution_levels": list(item.resolution_levels), "activation_profile": {"memory_bytes": item.activation_profile.memory_bytes}}

    def _semantic_transition(self, source: str, destination: str) -> dict[str, Any]:
        return {"transition_id": f"{source}-{destination}-v1", "source": source, "destination": destination, "input_contract": "SufficientStateV1", "output_contract": "SufficientStateV1", "projection": {"projection_id": f"{source}-{destination}", "required_fields": list(REQUIRED_STATE_FIELDS), "fallback": "FullSafeProjection"}, "preserved_invariants": list(REQUIRED_STATE_FIELDS), "required_effects": ["catalog.read", "universe.activate", "transition.execute", "universe.crystallize"], "budget": {"latency_ms": 100, "memory_bytes": 32 * 1024 * 1024, "transfer_bytes": 64 * 1024, "semantic_risk": 0.2, "fidelity": 1.0}}


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in re.findall(r"[\wÀ-ÿ]+", text))


def _enum_dict(value: Any) -> dict[str, Any]:
    result = asdict(value)
    for key, item in tuple(result.items()):
        if hasattr(item, "value"):
            result[key] = item.value
    return result
