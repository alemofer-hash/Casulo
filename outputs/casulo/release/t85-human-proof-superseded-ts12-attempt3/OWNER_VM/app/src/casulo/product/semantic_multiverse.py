from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


UNIVERSE_SCHEMA = "casulo.semantic-universe-manifest/1.0"
TRANSITION_RECEIPT_SCHEMA = "casulo.semantic-transition-receipt/1.0"
LIFECYCLE_RECEIPT_SCHEMA = "casulo.universe-lifecycle-receipt/1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_TOKEN = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


class SemanticMultiverseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


@dataclass(frozen=True, slots=True)
class ActivationProfile:
    memory_bytes: int
    wake_cost_ms: int
    warm_bytes: int

    def __post_init__(self) -> None:
        if type(self.memory_bytes) is not int or not 4096 <= self.memory_bytes <= 1 << 34:
            raise SemanticMultiverseError("SM110", "memory_bytes fora dos limites")
        if type(self.wake_cost_ms) is not int or self.wake_cost_ms < 0:
            raise SemanticMultiverseError("SM111", "wake_cost_ms inválido")
        if type(self.warm_bytes) is not int or not 0 <= self.warm_bytes <= self.memory_bytes:
            raise SemanticMultiverseError("SM112", "warm_bytes inválido")


@dataclass(frozen=True, slots=True)
class SemanticUniverseManifest:
    universe_id: str
    version: int
    content_hash: str
    parent_hashes: tuple[str, ...]
    semantic_address: tuple[str, ...]
    invariants: tuple[str, ...]
    variants_schema: Mapping[str, str]
    input_contracts: tuple[str, ...]
    output_contracts: tuple[str, ...]
    capabilities: tuple[str, ...]
    neighbors: tuple[str, ...]
    activation_profile: ActivationProfile
    resolution_levels: tuple[str, ...]
    license: str
    provenance: tuple[str, ...]
    signature: str | None
    migration_policy: str
    schema: str = UNIVERSE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != UNIVERSE_SCHEMA or not _ID.fullmatch(self.universe_id):
            raise SemanticMultiverseError("SM100", "schema ou universe_id inválido")
        if type(self.version) is not int or self.version < 1 or not _SHA256.fullmatch(self.content_hash):
            raise SemanticMultiverseError("SM101", "version ou content_hash inválido")
        for name, values, allow_empty in (
            ("parent_hashes", self.parent_hashes, True),
            ("semantic_address", self.semantic_address, False),
            ("invariants", self.invariants, False),
            ("input_contracts", self.input_contracts, False),
            ("output_contracts", self.output_contracts, False),
            ("capabilities", self.capabilities, True),
            ("neighbors", self.neighbors, True),
            ("resolution_levels", self.resolution_levels, False),
            ("provenance", self.provenance, False),
        ):
            if (not values and not allow_empty) or any(not str(item).strip() for item in values) or len(set(values)) != len(values):
                raise SemanticMultiverseError("SM102", f"{name} vazio ou duplicado")
        if any(not _SHA256.fullmatch(item) for item in self.parent_hashes):
            raise SemanticMultiverseError("SM103", "parent_hash inválido")
        if not self.license or not self.migration_policy:
            raise SemanticMultiverseError("SM104", "license/migration_policy ausente")
        if any(not key or not value for key, value in self.variants_schema.items()):
            raise SemanticMultiverseError("SM105", "variants_schema inválido")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticUniverseManifest":
        expected = {
            "schema", "universe_id", "version", "content_hash", "parent_hashes",
            "semantic_address", "invariants", "variants_schema", "input_contracts",
            "output_contracts", "capabilities", "neighbors", "activation_profile",
            "resolution_levels", "license", "provenance", "signature", "migration_policy",
        }
        if set(value) != expected:
            raise SemanticMultiverseError("SM106", "chaves do manifesto divergem")
        activation = value["activation_profile"]
        if not isinstance(activation, Mapping) or set(activation) != {"memory_bytes", "wake_cost_ms", "warm_bytes"}:
            raise SemanticMultiverseError("SM107", "activation_profile inválido")
        return cls(
            universe_id=str(value["universe_id"]), version=value["version"], content_hash=str(value["content_hash"]),
            parent_hashes=tuple(value["parent_hashes"]), semantic_address=tuple(value["semantic_address"]),
            invariants=tuple(value["invariants"]), variants_schema=dict(value["variants_schema"]),
            input_contracts=tuple(value["input_contracts"]), output_contracts=tuple(value["output_contracts"]),
            capabilities=tuple(value["capabilities"]), neighbors=tuple(value["neighbors"]),
            activation_profile=ActivationProfile(**activation), resolution_levels=tuple(value["resolution_levels"]),
            license=str(value["license"]), provenance=tuple(value["provenance"]),
            signature=None if value["signature"] is None else str(value["signature"]),
            migration_policy=str(value["migration_policy"]), schema=str(value["schema"]),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("parent_hashes", "semantic_address", "invariants", "input_contracts", "output_contracts", "capabilities", "neighbors", "resolution_levels", "provenance"):
            result[key] = list(result[key])
        return result

    @property
    def manifest_hash(self) -> str:
        return sha256_json(self.to_dict())


class ContentAddressedUniverseStore:
    """Immutable blob store with transactional staging and quarantine."""

    def __init__(self, root: Path, *, max_blob_bytes: int = 16 * 1024 * 1024) -> None:
        self.root = root.resolve()
        self.max_blob_bytes = max_blob_bytes
        self.blobs = self.root / "blobs"
        self.manifests = self.root / "manifests"
        self.deltas = self.root / "deltas"
        self.quarantine = self.root / "quarantine"
        for path in (self.blobs, self.manifests, self.deltas, self.quarantine):
            path.mkdir(parents=True, exist_ok=True)

    def publish_blob(self, data: bytes, *, expected_hash: str | None = None) -> tuple[str, bool]:
        if not data or len(data) > self.max_blob_bytes:
            raise SemanticMultiverseError("SM200", "blob vazio ou excessivo")
        digest = sha256_bytes(data)
        if expected_hash is not None and digest != expected_hash:
            self._quarantine(data, "hash-mismatch", digest)
            raise SemanticMultiverseError("SM201", "hash mismatch; blob em quarentena")
        target = self.blobs / digest
        if target.exists():
            if target.read_bytes() != data:
                raise SemanticMultiverseError("SM202", "colisão de conteúdo")
            return digest, True
        staging = self.root / f".stage-{uuid.uuid4().hex}"
        staging.write_bytes(data)
        if sha256_bytes(staging.read_bytes()) != digest:
            staging.unlink(missing_ok=True)
            raise SemanticMultiverseError("SM203", "staging divergiu")
        staging.replace(target)
        return digest, False

    def read_blob(self, digest: str) -> bytes:
        if not _SHA256.fullmatch(digest):
            raise SemanticMultiverseError("SM204", "digest inválido")
        path = self.blobs / digest
        if not path.is_file() or path.is_symlink():
            raise SemanticMultiverseError("SM205", "blob ausente")
        data = path.read_bytes()
        if sha256_bytes(data) != digest:
            quarantine_target = self.quarantine / f"corrupt-{digest}-{uuid.uuid4().hex}"
            shutil.copyfile(path, quarantine_target)
            raise SemanticMultiverseError("SM206", "blob corrompido; cópia em quarentena")
        return data

    def publish_manifest(self, manifest: SemanticUniverseManifest) -> Path:
        self.read_blob(manifest.content_hash)
        path = self.manifests / f"{manifest.universe_id}-v{manifest.version}-{manifest.manifest_hash}.json"
        payload = canonical_json(manifest.to_dict()) + b"\n"
        if path.exists() and path.read_bytes() != payload:
            raise SemanticMultiverseError("SM207", "manifesto imutável divergiu")
        if not path.exists():
            path.write_bytes(payload)
        return path

    def import_bundle(
        self,
        manifest_payload: Mapping[str, Any],
        blob: bytes,
        *,
        allowed_capabilities: frozenset[str],
        require_signature: bool = True,
    ) -> SemanticUniverseManifest:
        """Quarantine-first boundary. Imported content is never executable policy."""
        manifest_bytes = canonical_json(dict(manifest_payload))
        try:
            manifest = SemanticUniverseManifest.from_dict(manifest_payload)
            forbidden = set(manifest.capabilities) - allowed_capabilities
            if forbidden:
                raise SemanticMultiverseError("SM209", f"capability importada negada: {sorted(forbidden)}")
            if require_signature and not manifest.signature:
                raise SemanticMultiverseError("SM210", "assinatura importada ausente")
            if sha256_bytes(blob) != manifest.content_hash:
                raise SemanticMultiverseError("SM211", "conteúdo importado diverge do manifesto")
        except Exception:
            identity = sha256_bytes(manifest_bytes + b"\0" + blob)
            self._quarantine(manifest_bytes + b"\n" + blob, "import-rejected", identity)
            raise
        self.publish_blob(blob, expected_hash=manifest.content_hash)
        self.publish_manifest(manifest)
        return manifest

    def publish_delta(self, *, base_hash: str, delta: Mapping[str, Any], confirmed: bool) -> str:
        self.read_blob(base_hash)
        if not confirmed:
            raise SemanticMultiverseError("SM208", "delta não confirmado não pode ser publicado")
        payload = canonical_json({"schema": "casulo.universe-delta/1.0", "base_hash": base_hash, "delta": dict(delta)})
        digest = sha256_bytes(payload)
        target = self.deltas / f"{digest}.json"
        if not target.exists():
            target.write_bytes(payload + b"\n")
        return digest

    def gc_plan(self, protected_hashes: Iterable[str]) -> dict[str, Any]:
        protected = set(protected_hashes)
        candidates = sorted(path.name for path in self.blobs.iterdir() if path.is_file() and path.name not in protected)
        return {"schema": "casulo.gc-plan/1.0", "candidates": candidates, "protected_objects_untouched": True, "material_delete_executed": False}

    def _quarantine(self, data: bytes, reason: str, digest: str) -> None:
        (self.quarantine / f"{reason}-{digest}-{uuid.uuid4().hex}.bin").write_bytes(data)


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    version: int
    manifests: tuple[SemanticUniverseManifest, ...]
    index: Mapping[str, tuple[str, ...]]
    sha256: str


class GlobalSemanticCatalog:
    def __init__(self) -> None:
        self._snapshot = CatalogSnapshot(0, (), {}, sha256_json({"version": 0, "manifests": []}))

    @property
    def snapshot(self) -> CatalogSnapshot:
        return self._snapshot

    def rebuild(self, manifests: Iterable[SemanticUniverseManifest]) -> CatalogSnapshot:
        ordered = tuple(sorted(manifests, key=lambda item: item.universe_id))
        if not ordered or len({item.universe_id for item in ordered}) != len(ordered):
            raise SemanticMultiverseError("SM300", "catálogo vazio ou duplicado")
        ids = {item.universe_id for item in ordered}
        if any(set(item.neighbors) - ids for item in ordered):
            raise SemanticMultiverseError("SM301", "vizinho ausente")
        index: dict[str, set[str]] = {}
        for item in ordered:
            terms = set(item.semantic_address) | set(_tokens(item.universe_id))
            for term in terms:
                index.setdefault(term.casefold(), set()).add(item.universe_id)
        payload = {"version": self._snapshot.version + 1, "manifests": [item.to_dict() for item in ordered], "index": {key: sorted(value) for key, value in sorted(index.items())}}
        self._snapshot = CatalogSnapshot(payload["version"], ordered, {key: tuple(sorted(value)) for key, value in index.items()}, sha256_json(payload))
        return self._snapshot

    def query(self, text: str, *, limit: int = 5) -> tuple[tuple[SemanticUniverseManifest, float], ...]:
        terms = set(_tokens(text))
        counts: dict[str, int] = {}
        for term in terms:
            for universe_id in self._snapshot.index.get(term, ()):
                counts[universe_id] = counts.get(universe_id, 0) + 1
        by_id = {item.universe_id: item for item in self._snapshot.manifests}
        ranked = sorted(counts, key=lambda item: (-counts[item], item))[:limit]
        denominator = max(1, len(terms))
        return tuple((by_id[item], counts[item] / denominator) for item in ranked)


class UniverseState(StrEnum):
    ABSENT = "ABSENT"
    FROZEN = "FROZEN"
    WARMING = "WARMING"
    WARM = "WARM"
    ACTIVATING = "ACTIVATING"
    HOT = "HOT"
    QUIESCING = "QUIESCING"
    CRYSTALLIZING = "CRYSTALLIZING"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


@dataclass(slots=True)
class CancellationToken:
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    def checkpoint(self) -> None:
        if self.cancelled:
            raise SemanticMultiverseError("SM401", "operação cancelada")


@dataclass(frozen=True, slots=True)
class LifecycleReceipt:
    event_id: str
    universe_id: str
    before: UniverseState
    after: UniverseState
    reason: str
    memory_bytes: int
    monotonic_ns: int
    committed: bool
    schema: str = LIFECYCLE_RECEIPT_SCHEMA


class UniverseLifecycleManager:
    def __init__(self, manifests: Iterable[SemanticUniverseManifest], *, hot_limit: int = 3, memory_limit_bytes: int = 96 * 1024 * 1024) -> None:
        self.manifests = {item.universe_id: item for item in manifests}
        self.states = {item: UniverseState.FROZEN for item in self.manifests}
        self.hot_limit, self.memory_limit_bytes = hot_limit, memory_limit_bytes
        self.leases: dict[str, int] = {}
        self.last_used: dict[str, int] = {item: 0 for item in self.manifests}
        self.receipts: list[LifecycleReceipt] = []
        self._sequence = 0

    @property
    def hot(self) -> tuple[str, ...]:
        return tuple(sorted(item for item, state in self.states.items() if state is UniverseState.HOT))

    @property
    def hot_memory_bytes(self) -> int:
        return sum(self.manifests[item].activation_profile.memory_bytes for item in self.hot)

    def acquire(self, universe_id: str) -> None:
        if self.states.get(universe_id) is not UniverseState.HOT:
            raise SemanticMultiverseError("SM402", "lease exige universo HOT")
        self.leases[universe_id] = self.leases.get(universe_id, 0) + 1

    def release(self, universe_id: str) -> None:
        if self.leases.get(universe_id, 0) <= 0:
            raise SemanticMultiverseError("SM403", "lease ausente")
        self.leases[universe_id] -= 1

    def activate(self, universe_id: str, token: CancellationToken, *, reason: str = "route") -> tuple[LifecycleReceipt, ...]:
        if universe_id not in self.manifests:
            raise SemanticMultiverseError("SM404", "universo desconhecido")
        if self.states[universe_id] is UniverseState.HOT:
            self.last_used[universe_id] = time.monotonic_ns()
            return ()
        produced: list[LifecycleReceipt] = []
        try:
            token.checkpoint()
            produced.append(self._move(universe_id, UniverseState.WARMING, reason, False))
            token.checkpoint()
            produced.append(self._move(universe_id, UniverseState.WARM, reason, True))
            self._ensure_capacity(self.manifests[universe_id].activation_profile.memory_bytes, exclude=universe_id)
            token.checkpoint()
            produced.append(self._move(universe_id, UniverseState.ACTIVATING, reason, False))
            token.checkpoint()
            produced.append(self._move(universe_id, UniverseState.HOT, reason, True))
            self.last_used[universe_id] = time.monotonic_ns()
            return tuple(produced)
        except BaseException:
            before = self.states[universe_id]
            if before not in {UniverseState.FROZEN, UniverseState.HOT}:
                self.states[universe_id] = UniverseState.FROZEN
                self._sequence += 1
                rollback = LifecycleReceipt(f"lifecycle:{self._sequence}", universe_id, before, UniverseState.FROZEN, "rollback", self.hot_memory_bytes, time.monotonic_ns(), False)
                self.receipts.append(rollback)
            raise

    def quiesce(self, universe_id: str, *, crystallize: bool = False) -> tuple[LifecycleReceipt, ...]:
        if self.leases.get(universe_id, 0):
            raise SemanticMultiverseError("SM405", "universo leased não pode ser removido")
        state = self.states.get(universe_id)
        if state not in {UniverseState.HOT, UniverseState.WARM}:
            return ()
        receipts = [self._move(universe_id, UniverseState.QUIESCING, "pressure", False)]
        if crystallize:
            receipts.append(self._move(universe_id, UniverseState.CRYSTALLIZING, "confirmed-delta", False))
        receipts.append(self._move(universe_id, UniverseState.FROZEN, "pressure", True))
        return tuple(receipts)

    def restore_cold(self) -> None:
        for item, state in tuple(self.states.items()):
            if state not in {UniverseState.QUARANTINED, UniverseState.FAILED}:
                self.states[item] = UniverseState.FROZEN
        self.leases.clear()

    def _ensure_capacity(self, incoming: int, *, exclude: str) -> None:
        while len(self.hot) >= self.hot_limit or self.hot_memory_bytes + incoming > self.memory_limit_bytes:
            candidates = [item for item in self.hot if item != exclude and not self.leases.get(item, 0)]
            if not candidates:
                raise SemanticMultiverseError("SM406", "quota HOT sem candidato seguro para eviction")
            victim = min(candidates, key=lambda item: (self.last_used[item], item))
            self.quiesce(victim)

    def _move(self, universe_id: str, after: UniverseState, reason: str, committed: bool) -> LifecycleReceipt:
        before = self.states[universe_id]
        allowed = {
            UniverseState.FROZEN: {UniverseState.WARMING}, UniverseState.WARMING: {UniverseState.WARM},
            UniverseState.WARM: {UniverseState.ACTIVATING, UniverseState.QUIESCING}, UniverseState.ACTIVATING: {UniverseState.HOT},
            UniverseState.HOT: {UniverseState.QUIESCING}, UniverseState.QUIESCING: {UniverseState.CRYSTALLIZING, UniverseState.FROZEN},
            UniverseState.CRYSTALLIZING: {UniverseState.FROZEN},
        }
        if after not in allowed.get(before, set()):
            raise SemanticMultiverseError("SM407", f"transição lifecycle inválida {before}->{after}")
        self.states[universe_id] = after
        self._sequence += 1
        receipt = LifecycleReceipt(f"lifecycle:{self._sequence}", universe_id, before, after, reason, self.hot_memory_bytes, time.monotonic_ns(), committed)
        self.receipts.append(receipt)
        return receipt


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    universe_id: str
    relevance: float
    cost: float
    risk: float


@dataclass(frozen=True, slots=True)
class RouteDecision:
    query_hash: str
    route: tuple[str, ...]
    candidates: tuple[RouteCandidate, ...]
    margin: float
    clarification_required: bool
    explanation: str


class SparseSemanticRouter:
    def __init__(self, catalog: GlobalSemanticCatalog, *, minimum_margin: float = 0.08) -> None:
        self.catalog, self.minimum_margin = catalog, minimum_margin

    def route(self, query: str, *, allowed_capabilities: frozenset[str], start: str | None = None) -> RouteDecision:
        raw = self.catalog.query(query, limit=8)
        candidates: list[RouteCandidate] = []
        for manifest, relevance in raw:
            if set(manifest.capabilities) - allowed_capabilities:
                continue
            profile = manifest.activation_profile
            cost = profile.wake_cost_ms / 1000 + profile.memory_bytes / (1024**3)
            risk = max(0.0, 1.0 - relevance)
            candidates.append(RouteCandidate(manifest.universe_id, relevance, cost, risk))
        candidates.sort(key=lambda item: (-(item.relevance - item.cost - item.risk * 0.2), item.universe_id))
        if not candidates:
            raise SemanticMultiverseError("SM500", "nenhum universo permitido corresponde à intenção")
        scores = [item.relevance - item.cost - item.risk * 0.2 for item in candidates]
        margin = scores[0] - scores[1] if len(scores) > 1 else 1.0
        destination = candidates[0].universe_id
        route = self._shortest_path(start, destination) if start and start != destination else (destination,)
        clarification = len(scores) > 1 and margin < self.minimum_margin
        return RouteDecision(sha256_bytes(query.encode("utf-8")), route, tuple(candidates), margin, clarification, "baixa margem; confirmar domínio" if clarification else "rota lexical/custo/policy aprovada")

    def _shortest_path(self, start: str, destination: str) -> tuple[str, ...]:
        by_id = {item.universe_id: item for item in self.catalog.snapshot.manifests}
        if start not in by_id:
            raise SemanticMultiverseError("SM501", "universo inicial desconhecido")
        queue: list[tuple[float, tuple[str, ...], str]] = [(0.0, (start,), start)]
        seen: set[str] = set()
        while queue:
            cost, path, node = heapq.heappop(queue)
            if node == destination:
                return path
            if node in seen:
                continue
            seen.add(node)
            for neighbor in by_id[node].neighbors:
                if neighbor in by_id and neighbor not in seen:
                    profile = by_id[neighbor].activation_profile
                    heapq.heappush(queue, (cost + profile.wake_cost_ms + profile.memory_bytes / (1024**2), (*path, neighbor), neighbor))
        return (destination,)


@dataclass(frozen=True, slots=True)
class SufficientProjection:
    transition_id: str
    required_fields: tuple[str, ...]
    fallback_complete: bool = True

    def compile(self, state: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
        missing = tuple(field for field in self.required_fields if field not in state)
        if missing:
            raise SemanticMultiverseError("SM600", f"estado completo também não contém required fields: {missing}")
        return {field: state[field] for field in self.required_fields}, ()


@dataclass(frozen=True, slots=True)
class TransitionReceipt:
    transition_id: str
    source: str
    destination: str
    contract_version: str
    input_hash: str
    output_hash: str
    preserved_invariants: tuple[str, ...]
    omitted_fields: tuple[str, ...]
    uncertainty: float
    latency_ns: int
    bytes_read: int
    bytes_transferred: int
    capabilities_used: tuple[str, ...]
    provenance_root: str
    fallback_used: bool
    committed: bool
    schema: str = TRANSITION_RECEIPT_SCHEMA


class SemanticTransitionRuntime:
    def __init__(self) -> None:
        self.receipts: list[TransitionReceipt] = []

    def execute(
        self, *, transition_id: str, source: SemanticUniverseManifest,
        destination: SemanticUniverseManifest, state: Mapping[str, Any],
        projection: SufficientProjection, required_invariants: tuple[str, ...],
        allowed_capabilities: frozenset[str], provenance_root: str,
        token: CancellationToken, uncertainty: float = 0.0,
    ) -> tuple[dict[str, Any], TransitionReceipt]:
        token.checkpoint()
        if set(destination.capabilities) - allowed_capabilities or set(destination.capabilities) - set(source.capabilities):
            raise SemanticMultiverseError("SM601", "transição ampliaria capability")
        if not set(required_invariants) <= set(source.invariants) or not set(required_invariants) <= set(destination.invariants):
            raise SemanticMultiverseError("SM602", "invariante obrigatório não existe nos endpoints")
        started = time.monotonic_ns()
        input_payload = canonical_json(dict(state))
        projected, missing = projection.compile(state)
        token.checkpoint()
        output_payload = canonical_json(projected)
        receipt = TransitionReceipt(
            transition_id, source.universe_id, destination.universe_id, "1.0",
            sha256_bytes(input_payload), sha256_bytes(output_payload), required_invariants,
            tuple(sorted(set(state) - set(projected))), float(uncertainty), time.monotonic_ns() - started,
            len(input_payload), len(output_payload), tuple(sorted(destination.capabilities)), provenance_root,
            bool(missing), True,
        )
        self.receipts.append(receipt)
        return projected, receipt


class MemoryThermostat:
    def __init__(self, lifecycle: UniverseLifecycleManager) -> None:
        self.lifecycle = lifecycle

    def reconcile(self, desired: Sequence[str], token: CancellationToken) -> tuple[LifecycleReceipt, ...]:
        events: list[LifecycleReceipt] = []
        for item in desired:
            events.extend(self.lifecycle.activate(item, token, reason="thermostat"))
        for item in tuple(self.lifecycle.hot):
            if item not in desired and not self.lifecycle.leases.get(item, 0):
                events.extend(self.lifecycle.quiesce(item))
        return tuple(events)


class SemanticPrefetcher:
    def __init__(self, lifecycle: UniverseLifecycleManager, *, quota: int = 1) -> None:
        self.lifecycle, self.quota = lifecycle, quota

    def prefetch(self, candidates: Sequence[RouteCandidate], *, expected_latency_saved_ms: int, token: CancellationToken) -> tuple[str, ...]:
        warmed: list[str] = []
        for candidate in candidates[: self.quota]:
            profile = self.lifecycle.manifests[candidate.universe_id].activation_profile
            cost = profile.wake_cost_ms + profile.warm_bytes / (1024**2)
            if expected_latency_saved_ms <= cost:
                continue
            try:
                self.lifecycle.activate(candidate.universe_id, token, reason="prefetch")
            except SemanticMultiverseError as error:
                if error.code == "SM406":
                    break
                raise
            warmed.append(candidate.universe_id)
        return tuple(warmed)


@dataclass(frozen=True, slots=True)
class Wormhole:
    wormhole_id: str
    source: str
    destination: str
    via: tuple[str, ...]
    equivalence_receipt_hash: str
    active: bool


class WormholeRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Wormhole] = {}

    def promote(self, *, source: str, destination: str, via: tuple[str, ...], equivalence_pass: bool, provenance_preserved: bool, receipt_hash: str) -> Wormhole:
        if not equivalence_pass or not provenance_preserved or not _SHA256.fullmatch(receipt_hash):
            raise SemanticMultiverseError("SM700", "wormhole sem equivalência/proveniência")
        identity = sha256_json({"source": source, "destination": destination, "via": via})
        item = Wormhole(f"wormhole:{identity[:16]}", source, destination, via, receipt_hash, True)
        self._items[item.wormhole_id] = item
        return item

    def rollback(self, wormhole_id: str) -> Wormhole:
        item = self._items[wormhole_id]
        reverted = Wormhole(item.wormhole_id, item.source, item.destination, item.via, item.equivalence_receipt_hash, False)
        self._items[wormhole_id] = reverted
        return reverted


@dataclass(frozen=True, slots=True)
class EquivalenceResult:
    hard_contract_pass: bool
    semantic_differences: tuple[str, ...]
    reference_hash: str
    factorized_hash: str
    human_review_required: bool


class OperationalEquivalenceHarness:
    def compare(self, reference: Mapping[str, Any], factorized: Mapping[str, Any], *, hard_fields: Iterable[str], generative_fields: Iterable[str] = ()) -> EquivalenceResult:
        hard = tuple(hard_fields)
        missing = tuple(key for key in hard if reference.get(key) != factorized.get(key))
        generative = tuple(key for key in generative_fields if reference.get(key) != factorized.get(key))
        return EquivalenceResult(not missing, (*missing, *generative), sha256_json(dict(reference)), sha256_json(dict(factorized)), bool(generative))


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN.findall(text))
