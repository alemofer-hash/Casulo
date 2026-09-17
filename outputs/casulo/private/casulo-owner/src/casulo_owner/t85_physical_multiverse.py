from __future__ import annotations

import gc
import hashlib
import json
import mmap
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import psutil

from casulo.product.semantic_multiverse import (
    SemanticMultiverseError,
    SemanticUniverseManifest,
    canonical_json,
    sha256_bytes,
)
from casulo.t.productive import ProductiveTCall, ProductiveTError, ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder


PHYSICAL_BUNDLE_SCHEMA = "casulo.universe-bundle/1.0"
FOREIGN_RECEIPT_SCHEMA = "casulo.universe-foreign-receipt/1.0"
REQUIRED_BUNDLE_ASSETS = (
    "manifest",
    "t_modules_or_tcap",
    "schemas",
    "domain_verifiers",
    "retrieval_indexes",
    "tool_manifests",
    "sufficient_state",
    "tests",
    "provenance",
)


class PhysicalMultiverseError(RuntimeError):
    pass


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise PhysicalMultiverseError(f"immutable path diverged: {path.name}")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _asset_payloads(manifest: SemanticUniverseManifest, policy_source: bytes) -> dict[str, bytes]:
    universe_id = manifest.universe_id
    return {
        "manifest": canonical_json(manifest.to_dict()),
        "t_modules_or_tcap": canonical_json({
            "schema": "casulo.universe-t-binding/1.0",
            "lifecycle_policy_sha256": sha256_bytes(policy_source),
            "entrypoint": "owner.multiverse.lifecycle_policy::decide",
            "binding": "shared-content-addressed-policy",
        }),
        "schemas": canonical_json({
            "schema": "casulo.universe-schemas/1.0",
            "universe_id": universe_id,
            "inputs": list(manifest.input_contracts),
            "outputs": list(manifest.output_contracts),
            "variants": dict(manifest.variants_schema),
        }),
        "domain_verifiers": canonical_json({
            "schema": "casulo.universe-verifiers/1.0",
            "universe_id": universe_id,
            "required_invariants": list(manifest.invariants),
            "failure_mode": "FAIL_CLOSED",
        }),
        "retrieval_indexes": canonical_json({
            "schema": "casulo.universe-index/1.0",
            "universe_id": universe_id,
            "terms": sorted(set(manifest.semantic_address)),
            "postings": {term: [universe_id] for term in sorted(set(manifest.semantic_address))},
        }),
        "tool_manifests": canonical_json({
            "schema": "casulo.universe-tools/1.0",
            "universe_id": universe_id,
            "capabilities": list(manifest.capabilities),
            "authority": "FOREIGN_PRIMITIVE_ONLY",
        }),
        "sufficient_state": canonical_json({
            "schema": "casulo.sufficient-state-contract/1.0",
            "universe_id": universe_id,
            "required_fields": list(manifest.invariants),
            "unknown_policy": "BLOCK",
        }),
        "tests": canonical_json({
            "schema": "casulo.universe-probes/1.0",
            "universe_id": universe_id,
            "cases": ["activate", "hibernate", "corruption", "capability_denial", "cancel"],
        }),
        "provenance": canonical_json({
            "schema": "casulo.universe-provenance/1.0",
            "universe_id": universe_id,
            "lineage": list(manifest.provenance),
            "content_hash": manifest.content_hash,
            "license": manifest.license,
        }),
    }


def build_physical_universe_bundles(
    root: Path,
    manifests: Iterable[SemanticUniverseManifest],
    *,
    policy_source: Path,
) -> Path:
    """Build compact, content-addressed bundles; no bytes are added for sizing."""
    root = root.resolve()
    objects = root / "objects"
    bundles = root / "bundles"
    policy = policy_source.read_bytes()
    catalog: list[dict[str, Any]] = []
    for manifest in sorted(manifests, key=lambda item: item.universe_id):
        assets: dict[str, dict[str, Any]] = {}
        for name, payload in _asset_payloads(manifest, policy).items():
            digest = sha256_bytes(payload)
            _write_immutable(objects / digest, payload)
            assets[name] = {"sha256": digest, "bytes": len(payload)}
        unsigned = {
            "schema": PHYSICAL_BUNDLE_SCHEMA,
            "universe_id": manifest.universe_id,
            "version": manifest.version,
            "capabilities": list(manifest.capabilities),
            "assets": assets,
            "artificial_padding": False,
        }
        payload = canonical_json({**unsigned, "bundle_hash": sha256_bytes(canonical_json(unsigned))}) + b"\n"
        path = bundles / f"{manifest.universe_id}.json"
        _write_immutable(path, payload)
        catalog.append({
            "universe_id": manifest.universe_id,
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_bytes(payload),
        })
    catalog_payload = canonical_json({"schema": "casulo.universe-bundle-catalog/1.0", "bundles": catalog}) + b"\n"
    _write_immutable(root / "catalog.json", catalog_payload)
    return root / "catalog.json"


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    monotonic_ns: int
    rss_bytes: int
    private_working_set_bytes: int | None
    commit_bytes: int | None
    mapped_bytes: int
    cache_bytes: int
    handle_count: int | None
    disk_read_bytes: int
    cpu_time_seconds: float
    model_calls: int
    tokens: int


@dataclass(frozen=True, slots=True)
class ForeignLifecycleReceipt:
    operation_id: str
    universe_id: str
    action: str
    before: str
    after: str
    bundle_sha256: str
    t_decision_receipt_hash: str
    observation_before: ResourceObservation
    observation_after: ResourceObservation
    activation_latency_ns: int
    bytes_read: int
    constraints_hash: str
    provenance_hash: str
    previous_receipt_hash: str
    receipt_hash: str
    schema: str = FOREIGN_RECEIPT_SCHEMA


class PhysicalUniverseStore:
    """Read-only mmap primitive. It executes T decisions but makes none."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        catalog = json.loads((self.root / "catalog.json").read_text(encoding="utf-8"))
        if catalog.get("schema") != "casulo.universe-bundle-catalog/1.0":
            raise PhysicalMultiverseError("bundle catalog schema invalid")
        self.catalog = {item["universe_id"]: item for item in catalog["bundles"]}
        self.states = {key: "FROZEN" for key in self.catalog}
        self.leases = {key: 0 for key in self.catalog}
        self._maps: dict[str, mmap.mmap] = {}
        self._map_refs: dict[str, int] = {}
        self._cache: dict[str, Any] = {}
        self._cache_refs: dict[str, int] = {}
        self._bundle_assets: dict[str, tuple[str, ...]] = {}
        self._process = psutil.Process()

    def _bundle(self, universe_id: str) -> tuple[dict[str, Any], bytes]:
        entry = self.catalog.get(universe_id)
        if entry is None:
            raise PhysicalMultiverseError("unknown universe")
        path = (self.root / entry["path"]).resolve()
        if not path.is_relative_to(self.root) or path.is_symlink():
            raise PhysicalMultiverseError("bundle path escaped root")
        payload = path.read_bytes()
        if sha256_bytes(payload) != entry["sha256"]:
            raise PhysicalMultiverseError("bundle manifest hash mismatch")
        document = json.loads(payload)
        if document.get("schema") != PHYSICAL_BUNDLE_SCHEMA:
            raise PhysicalMultiverseError("bundle schema invalid")
        if set(document.get("assets", {})) != set(REQUIRED_BUNDLE_ASSETS):
            raise PhysicalMultiverseError("bundle assets incomplete")
        if document.get("artificial_padding") is not False:
            raise PhysicalMultiverseError("artificial padding prohibited")
        unsigned = {key: value for key, value in document.items() if key != "bundle_hash"}
        if document.get("bundle_hash") != sha256_bytes(canonical_json(unsigned)):
            raise PhysicalMultiverseError("bundle self hash invalid")
        return document, payload

    def validate(self, universe_id: str) -> bool:
        try:
            document, _ = self._bundle(universe_id)
            for item in document["assets"].values():
                path = (self.root / "objects" / item["sha256"]).resolve()
                if not path.is_relative_to(self.root) or path.is_symlink():
                    return False
                payload = path.read_bytes()
                if len(payload) != item["bytes"] or sha256_bytes(payload) != item["sha256"]:
                    return False
            return True
        except (OSError, ValueError, TypeError, KeyError, PhysicalMultiverseError):
            return False

    def capabilities(self, universe_id: str) -> frozenset[str]:
        document, _ = self._bundle(universe_id)
        return frozenset(str(item) for item in document["capabilities"])

    def observe(self, *, model_calls: int = 0, tokens: int = 0) -> ResourceObservation:
        memory = self._process.memory_info()
        try:
            full = self._process.memory_full_info()
        except (psutil.Error, AttributeError):
            full = memory
        private = getattr(full, "private", None)
        commit = getattr(memory, "pagefile", None)
        try:
            handles = self._process.num_handles() if os.name == "nt" else self._process.num_fds()
        except (psutil.Error, AttributeError):
            handles = None
        try:
            disk_read = self._process.io_counters().read_bytes
        except (psutil.Error, AttributeError):
            disk_read = 0
        cpu = self._process.cpu_times()
        return ResourceObservation(
            time.monotonic_ns(), int(memory.rss), None if private is None else int(private),
            None if commit is None else int(commit), self.mapped_bytes, self.cache_bytes,
            handles, int(disk_read), float(cpu.user + cpu.system), model_calls, tokens,
        )

    @property
    def mapped_bytes(self) -> int:
        return sum(len(item) for item in self._maps.values())

    @property
    def cache_bytes(self) -> int:
        return sum(len(canonical_json(value)) for value in self._cache.values())

    @property
    def managed_bytes(self) -> int:
        return self.mapped_bytes + self.cache_bytes

    def projected_managed_bytes(self, universes: Sequence[str]) -> int:
        """Exact compact asset bytes, counted once across content-addressed refs."""
        digests: set[str] = set()
        for universe_id in universes:
            document, _ = self._bundle(universe_id)
            digests.update(item["sha256"] for item in document["assets"].values())
        total = 0
        for digest in digests:
            payload = (self.root / "objects" / digest).read_bytes()
            if sha256_bytes(payload) != digest:
                raise PhysicalMultiverseError("projected managed bytes found corruption")
            total += len(payload) * 2  # read-only mmap plus parsed canonical cache
        return total

    def reference_read(self, universe_id: str) -> tuple[str, int]:
        document, manifest_payload = self._bundle(universe_id)
        total = len(manifest_payload)
        for item in document["assets"].values():
            payload = (self.root / "objects" / item["sha256"]).read_bytes()
            if sha256_bytes(payload) != item["sha256"]:
                raise PhysicalMultiverseError("reference read found corruption")
            total += len(payload)
        return str(document["bundle_hash"]), total

    def activate(self, universe_id: str, *, t_receipt_hash: str, constraints_hash: str, provenance_hash: str, previous_receipt_hash: str) -> ForeignLifecycleReceipt:
        if self.states[universe_id] == "HOT":
            raise PhysicalMultiverseError("duplicate activation denied")
        before_observation = self.observe()
        document, manifest_payload = self._bundle(universe_id)
        started = time.monotonic_ns()
        acquired: list[str] = []
        cached: list[str] = []
        try:
            self.states[universe_id] = "WARMING"
            asset_hashes = tuple(item["sha256"] for item in document["assets"].values())
            for digest in asset_hashes:
                if digest not in self._maps:
                    path = self.root / "objects" / digest
                    handle = path.open("rb")
                    try:
                        mapped = mmap.mmap(handle.fileno(), length=0, access=mmap.ACCESS_READ)
                    finally:
                        handle.close()
                    if sha256_bytes(mapped[:]) != digest:
                        mapped.close()
                        raise PhysicalMultiverseError("mapped asset hash mismatch")
                    self._maps[digest] = mapped
                    self._map_refs[digest] = 0
                self._map_refs[digest] += 1
                acquired.append(digest)
            self.states[universe_id] = "WARM"
            self.states[universe_id] = "ACTIVATING"
            for digest in asset_hashes:
                if digest not in self._cache:
                    self._cache[digest] = json.loads(self._maps[digest][:])
                    self._cache_refs[digest] = 0
                self._cache_refs[digest] += 1
                cached.append(digest)
            self._bundle_assets[universe_id] = asset_hashes
            self.states[universe_id] = "HOT"
        except BaseException:
            for digest in reversed(cached):
                self._decrement_cache(digest)
            for digest in reversed(acquired):
                self._decrement_map(digest)
            self.states[universe_id] = "FROZEN"
            raise
        after = self.observe()
        return self._receipt(
            universe_id, "ACTIVATE", "FROZEN", "HOT", document, t_receipt_hash,
            before_observation, after, time.monotonic_ns() - started,
            len(manifest_payload) + sum(item["bytes"] for item in document["assets"].values()),
            constraints_hash, provenance_hash, previous_receipt_hash,
        )

    def hibernate(self, universe_id: str, *, t_receipt_hash: str, constraints_hash: str, provenance_hash: str, previous_receipt_hash: str) -> ForeignLifecycleReceipt:
        if self.states[universe_id] != "HOT" or self.leases[universe_id]:
            raise PhysicalMultiverseError("hibernate requires unleased HOT universe")
        before_observation = self.observe()
        document, _ = self._bundle(universe_id)
        started = time.monotonic_ns()
        self.states[universe_id] = "HIBERNATING"
        for digest in self._bundle_assets.pop(universe_id):
            self._decrement_cache(digest)
            self._decrement_map(digest)
        self.states[universe_id] = "FROZEN"
        gc.collect()
        after = self.observe()
        return self._receipt(
            universe_id, "HIBERNATE", "HOT", "FROZEN", document, t_receipt_hash,
            before_observation, after, time.monotonic_ns() - started, 0,
            constraints_hash, provenance_hash, previous_receipt_hash,
        )

    def acquire(self, universe_id: str) -> None:
        if self.states[universe_id] != "HOT":
            raise PhysicalMultiverseError("lease requires HOT universe")
        self.leases[universe_id] += 1

    def release(self, universe_id: str) -> None:
        if self.leases[universe_id] <= 0:
            raise PhysicalMultiverseError("lease absent")
        self.leases[universe_id] -= 1

    def close(self) -> None:
        if any(self.leases.values()):
            raise PhysicalMultiverseError("cannot close leased universes")
        for universe_id in tuple(self.catalog):
            if self.states[universe_id] == "HOT":
                for digest in self._bundle_assets.pop(universe_id):
                    self._decrement_cache(digest)
                    self._decrement_map(digest)
                self.states[universe_id] = "FROZEN"
        gc.collect()

    def _decrement_cache(self, digest: str) -> None:
        self._cache_refs[digest] -= 1
        if self._cache_refs[digest] == 0:
            del self._cache_refs[digest]
            del self._cache[digest]

    def _decrement_map(self, digest: str) -> None:
        self._map_refs[digest] -= 1
        if self._map_refs[digest] == 0:
            del self._map_refs[digest]
            self._maps.pop(digest).close()

    @staticmethod
    def _receipt(
        universe_id: str, action: str, before: str, after: str,
        document: Mapping[str, Any], t_receipt_hash: str,
        observation_before: ResourceObservation, observation_after: ResourceObservation,
        latency: int, bytes_read: int, constraints_hash: str, provenance_hash: str,
        previous_receipt_hash: str,
    ) -> ForeignLifecycleReceipt:
        seed = {
            "schema": FOREIGN_RECEIPT_SCHEMA,
            "operation_id": f"foreign:{time.monotonic_ns()}",
            "universe_id": universe_id,
            "action": action,
            "before": before,
            "after": after,
            "bundle_sha256": str(document["bundle_hash"]),
            "t_decision_receipt_hash": t_receipt_hash,
            "observation_before": asdict(observation_before),
            "observation_after": asdict(observation_after),
            "activation_latency_ns": latency,
            "bytes_read": bytes_read,
            "constraints_hash": constraints_hash,
            "provenance_hash": provenance_hash,
            "previous_receipt_hash": previous_receipt_hash,
        }
        return ForeignLifecycleReceipt(
            operation_id=seed["operation_id"], universe_id=universe_id, action=action,
            before=before, after=after, bundle_sha256=seed["bundle_sha256"],
            t_decision_receipt_hash=t_receipt_hash,
            observation_before=observation_before, observation_after=observation_after,
            activation_latency_ns=latency, bytes_read=bytes_read,
            constraints_hash=constraints_hash, provenance_hash=provenance_hash,
            previous_receipt_hash=previous_receipt_hash,
            receipt_hash=sha256_bytes(canonical_json(seed)),
        )


class T85PhysicalMultiverse:
    def __init__(
        self,
        runtime: Path,
        tcap: Path,
        bundle_root: Path,
        receipt_root: Path,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        minimum_residence_ns: int = 100_000_000,
        theta_off: float = 0.50,
        theta_on: float = 0.70,
    ) -> None:
        if not 0 <= theta_off < theta_on <= 1:
            raise PhysicalMultiverseError("thermostat hysteresis invalid")
        self.store = PhysicalUniverseStore(bundle_root)
        self.root = receipt_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.executor = ProductiveTExecutor(runtime, tcap, self.root / "t-decisions")
        self.clock_ns = clock_ns
        self.minimum_residence_ns = minimum_residence_ns
        self.theta_off, self.theta_on = theta_off, theta_on
        self.hot_since: dict[str, int] = {}
        self.sequence = 0
        self.previous_t = "0" * 64
        self.previous_foreign = "0" * 64
        self.foreign_receipts: list[ForeignLifecycleReceipt] = []

    @staticmethod
    def build_policy(source: Path, output: Path) -> Path:
        if output.exists():
            return output
        return TcapV2Builder().build(
            (source,), output,
            entry_module="owner.multiverse.lifecycle_policy", entry_function="decide",
            tests={"properties": ["trusted_route", "bundle_integrity", "capability_non_amplification", "lease_safe_hibernate"]},
        ).directory

    def activate(
        self,
        universe_id: str,
        *,
        allowed_capabilities: frozenset[str],
        constraints: Sequence[str],
        provenance: Sequence[str],
        trusted_route: bool = True,
        cancelled: bool = False,
    ) -> ForeignLifecycleReceipt | None:
        if self.store.states.get(universe_id) == "HOT":
            return None
        valid = self.store.validate(universe_id)
        try:
            capabilities = self.store.capabilities(universe_id)
        except PhysicalMultiverseError:
            capabilities = frozenset({"invalid.bundle"})
        call = self._decide(
            universe_id, "ACTIVATE", trusted_route=trusted_route, bundle_valid=valid,
            capability_safe=not (capabilities - allowed_capabilities), can_hibernate=False,
            sufficient_state_valid=True, cancelled=cancelled,
        )
        self._require(call, "ACTIVATE")
        receipt = self.store.activate(
            universe_id, t_receipt_hash=str(call.receipt["receipt_hash"]),
            constraints_hash=sha256_bytes(canonical_json(list(constraints))),
            provenance_hash=sha256_bytes(canonical_json(list(provenance))),
            previous_receipt_hash=self.previous_foreign,
        )
        self._persist_foreign(receipt)
        self.hot_since[universe_id] = self.clock_ns()
        return receipt

    def hibernate(
        self,
        universe_id: str,
        *,
        sufficient_state: Mapping[str, Any],
        constraints: Sequence[str],
        provenance: Sequence[str],
        force_after_residence: bool = False,
    ) -> ForeignLifecycleReceipt | None:
        if self.store.states.get(universe_id) != "HOT":
            return None
        elapsed = self.clock_ns() - self.hot_since.get(universe_id, self.clock_ns())
        can_hibernate = self.store.leases[universe_id] == 0 and (force_after_residence or elapsed >= self.minimum_residence_ns)
        required = ("intent", "constraints", "units", "uncertainty", "provenance")
        state_valid = all(field in sufficient_state for field in required)
        call = self._decide(
            universe_id, "HIBERNATE", trusted_route=True, bundle_valid=True,
            capability_safe=True, can_hibernate=can_hibernate, cancelled=False,
            sufficient_state_valid=state_valid,
        )
        self._require(call, "HIBERNATE")
        state_payload = canonical_json({field: sufficient_state[field] for field in required})
        state_hash = sha256_bytes(state_payload)
        _write_immutable(self.root / "sufficient-state" / f"{universe_id}-{state_hash}.json", state_payload + b"\n")
        receipt = self.store.hibernate(
            universe_id, t_receipt_hash=str(call.receipt["receipt_hash"]),
            constraints_hash=sha256_bytes(canonical_json(list(constraints))),
            provenance_hash=sha256_bytes(canonical_json(list(provenance))),
            previous_receipt_hash=self.previous_foreign,
        )
        self._persist_foreign(receipt)
        self.hot_since.pop(universe_id, None)
        return receipt

    def reconcile(
        self,
        desired: Sequence[str],
        *,
        allowed_capabilities: frozenset[str],
        sufficient_state: Mapping[str, Any],
        constraints: Sequence[str],
        provenance: Sequence[str],
    ) -> tuple[ForeignLifecycleReceipt, ...]:
        desired_set = set(desired)
        if not desired_set or desired_set - set(self.store.catalog):
            raise PhysicalMultiverseError("thermostat desired set invalid")
        receipts: list[ForeignLifecycleReceipt] = []
        for universe_id in desired:
            receipt = self.activate(
                universe_id, allowed_capabilities=allowed_capabilities,
                constraints=constraints, provenance=provenance,
            )
            if receipt is not None:
                receipts.append(receipt)
        capacity = self.store.projected_managed_bytes(tuple(self.store.catalog))
        pressure = self.store.managed_bytes / max(1, capacity) >= self.theta_on
        for universe_id in tuple(sorted(self.store.catalog)):
            if self.store.states[universe_id] != "HOT" or universe_id in desired_set:
                continue
            elapsed = self.clock_ns() - self.hot_since.get(universe_id, self.clock_ns())
            obsolete = elapsed >= self.minimum_residence_ns
            if pressure or obsolete:
                receipt = self.hibernate(
                    universe_id, sufficient_state=sufficient_state,
                    constraints=constraints, provenance=provenance,
                    force_after_residence=pressure and obsolete,
                )
                if receipt is not None:
                    receipts.append(receipt)
                pressure = self.store.managed_bytes / max(1, capacity) > self.theta_off
        return tuple(receipts)

    def _decide(self, universe_id: str, action: str, **payload: Any) -> ProductiveTCall:
        self.sequence += 1
        call_id = f"lifecycle.{self.sequence:08d}"
        call = self.executor.execute(
            "owner.multiverse.lifecycle_policy", "decide", {"action": action, **payload},
            call_id=call_id, surface_id="universe_lifecycle",
            scope_id=f"universe:{universe_id}", previous_receipt_hash=self.previous_t,
        )
        target = self.root / "t-decision-receipts" / f"{call_id}.receipt.json"
        _write_immutable(target, canonical_json({"observable": dict(call.observable), "receipt": dict(call.receipt)}) + b"\n")
        self.previous_t = str(call.receipt["receipt_hash"])
        return call

    @staticmethod
    def _require(call: ProductiveTCall, expected: str) -> None:
        result = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") != expected:
            raise ProductiveTError(f"T lifecycle denied: {result.get('value')}")

    def _persist_foreign(self, receipt: ForeignLifecycleReceipt) -> None:
        if receipt.previous_receipt_hash != self.previous_foreign:
            raise PhysicalMultiverseError("foreign receipt chain diverged")
        path = self.root / "foreign-receipts" / f"{len(self.foreign_receipts) + 1:08d}.json"
        _write_immutable(path, canonical_json(asdict(receipt)) + b"\n")
        self.foreign_receipts.append(receipt)
        self.previous_foreign = receipt.receipt_hash

    def close(self) -> None:
        self.store.close()
