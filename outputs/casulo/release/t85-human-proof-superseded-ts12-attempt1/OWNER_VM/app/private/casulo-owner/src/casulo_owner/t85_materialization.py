from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from casulo.product.domain import CreationSpec, CreationState, canonical_json
from casulo.product.materializer import MaterializationError
from casulo.product.simulation import SimulationReceipt
from casulo.product.sovereign_materializer import (
    SovereignMaterializationReceipt,
    SovereignTAgentBundle,
    build_staged_payloads,
    publish_payloads,
    sha256_bytes,
    sha256_file,
)
from casulo.product.t_forge import ForgeReceipt
from casulo.t.productive import ProductiveTCall, ProductiveTError, ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder


class T85MaterializationDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class MaterializationAuthorityResult:
    receipt: SovereignMaterializationReceipt
    prepare: ProductiveTCall
    seal: ProductiveTCall
    publish: ProductiveTCall
    candidate_sha256: str


def candidate_hash(payloads: Mapping[str, bytes]) -> str:
    inventory = {name: sha256_bytes(payload) for name, payload in sorted(payloads.items())}
    return sha256_bytes(canonical_json(inventory))


class T85SovereignMaterializer:
    """T owns PREPARE/SEAL/PUBLISH; Python is the bounded atomic primitive."""

    def __init__(self, runtime: Path, tcap: Path, output_root: Path, receipt_root: Path) -> None:
        self.output_root = output_root.resolve()
        self.receipt_root = receipt_root.resolve()
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.executor = ProductiveTExecutor(runtime, tcap, self.receipt_root / "inputs")
        self.sequence = 0
        self.previous = "0" * 64

    @staticmethod
    def build_policy(source: Path, output: Path) -> Path:
        if output.exists():
            return output
        return TcapV2Builder().build(
            (source,), output,
            entry_module="owner.materialization.lifecycle", entry_function="decide",
            tests={"properties": ["human_approval", "simulation_pass", "secret_and_effect_denial", "hash_seal", "atomic_publish"]},
        ).directory

    def materialize(
        self,
        creation: CreationSpec,
        *,
        forge_receipt: ForgeReceipt,
        simulation_receipt: SimulationReceipt,
        agent: SovereignTAgentBundle,
        requirement_graph: Mapping[str, Any],
        evidence_receipts: Mapping[str, Any],
        previous_fulfillment: str,
        human_approved: bool,
        cancelled: bool = False,
    ) -> MaterializationAuthorityResult:
        effects_safe = (
            creation.state is CreationState.AGREEMENT
            and simulation_receipt.creation_id == creation.creation_id
            and simulation_receipt.status == "PASS"
            and not simulation_receipt.real_effects_executed
            and not _contains_secret(creation.to_dict())
        )
        prepare = self._decision(
            "PREPARE", previous_fulfillment, human_approved, simulation_receipt.status,
            effects_safe, "preflight", True, False, cancelled,
        )
        self._require(prepare, "PREPARED")
        provisional = build_staged_payloads(
            creation, forge_receipt, simulation_receipt, agent,
            requirement_graph=requirement_graph, evidence_receipts=evidence_receipts,
            t_receipt_hashes=(str(prepare.receipt["receipt_hash"]),),
        )
        provisional_hash = candidate_hash(provisional)
        seal = self._decision(
            "SEAL", "PREPARED", human_approved, simulation_receipt.status,
            effects_safe, provisional_hash, candidate_hash(provisional) == provisional_hash,
            False, cancelled,
        )
        self._require(seal, "SEALED")
        payloads = build_staged_payloads(
            creation, forge_receipt, simulation_receipt, agent,
            requirement_graph=requirement_graph, evidence_receipts=evidence_receipts,
            t_receipt_hashes=(str(prepare.receipt["receipt_hash"]), str(seal.receipt["receipt_hash"])),
        )
        final_hash = candidate_hash(payloads)
        publish = self._decision(
            "PUBLISH", "SEALED", human_approved, simulation_receipt.status,
            effects_safe, final_hash, candidate_hash(payloads) == final_hash,
            True, cancelled, grants=("manifest",),
        )
        self._require(publish, "PUBLISH")
        manifest = json.loads(payloads["MANIFEST.json"])
        package_id = str(manifest["package_id"])
        destination, archive = publish_payloads(self.output_root, package_id, payloads)
        receipt = SovereignMaterializationReceipt(
            package_id, destination, archive, sha256_file(archive),
            sha256_bytes(payloads["MANIFEST.json"]),
            tuple(str(call.receipt["receipt_hash"]) for call in (prepare, seal, publish)),
        )
        summary = {
            "schema": "casulo.t85-materialization-authority/1.0",
            "package_id": package_id,
            "candidate_sha256": final_hash,
            "archive_sha256": receipt.archive_sha256,
            "T_decision_receipts": list(receipt.t_decision_receipt_hashes),
            "publish_receipt_external": True,
            "real_effects_executed": 0,
        }
        _write_immutable(self.receipt_root / "materialization-authority.json", canonical_json(summary) + b"\n")
        return MaterializationAuthorityResult(receipt, prepare, seal, publish, final_hash)

    def _decision(
        self,
        action: str,
        previous: str,
        human_approved: bool,
        simulation_status: str,
        effects_safe: bool,
        digest: str,
        digest_valid: bool,
        atomic_ready: bool,
        cancelled: bool,
        *,
        grants: tuple[str, ...] = (),
    ) -> ProductiveTCall:
        self.sequence += 1
        call_id = f"materialization.{self.sequence:08d}"
        call = self.executor.execute(
            "owner.materialization.lifecycle", "decide",
            {
                "action": action, "previous": previous, "human_approved": human_approved,
                "simulation_status": simulation_status, "effects_safe": effects_safe,
                "candidate_hash": digest, "candidate_hash_valid": digest_valid,
                "atomic_ready": atomic_ready, "cancelled": cancelled,
            },
            call_id=call_id, surface_id="publish_commit", scope_id="materialization:owner",
            grants=grants, previous_receipt_hash=self.previous,
        )
        target = self.receipt_root / "t-receipts" / f"{call_id}.json"
        _write_immutable(target, canonical_json({"observable": dict(call.observable), "receipt": dict(call.receipt)}) + b"\n")
        self.previous = str(call.receipt["receipt_hash"])
        return call

    @staticmethod
    def _require(call: ProductiveTCall, expected: str) -> None:
        result: Mapping[str, Any] = call.observable.get("result", {})
        if result.get("kind") != "ok" or result.get("value") != expected:
            raise T85MaterializationDenied(f"T materialization denied: {result.get('value')}")


def _contains_secret(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).casefold()
    markers = ("api_key", "private_key", "access_token", "refresh_token", "-----begin private key-----")
    return any(marker in text for marker in markers)


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise MaterializationError("immutable authority evidence diverged")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
