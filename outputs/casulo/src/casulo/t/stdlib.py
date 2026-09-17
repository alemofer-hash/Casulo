from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .authority import canonical_sha256
from .v2_tcap import verify_tcap_v2


class TStandardLibraryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TStage:
    module: str
    surface_id: str
    fixed_input: Mapping[str, Any]
    grants: tuple[str, ...] = ()


STAGES = (
    TStage("t.core.result", "agent_behavior", {"status": "PASS"}),
    TStage("t.core.collections", "hard_requirement_fulfillment", {"statuses": ["PASS", "PASS"]}),
    TStage("t.core.canonical", "agent_behavior", {"schema_supported": True}),
    TStage("t.casulo.intent", "material_intent", {"confirmed": True, "material": True}),
    TStage("t.casulo.requirements", "hard_requirement_fulfillment", {"hard_statuses": ["PASS", "PASS"]}),
    TStage("t.casulo.capabilities", "capabilities_effects", {"requested": ["simulation", "manifest"], "granted": ["simulation", "manifest"]}),
    TStage("t.casulo.memory_policy", "memory_governance", {"project_id": "project:alpha", "expected_project_id": "project:alpha", "consent": True}),
    TStage("t.casulo.jobs", "jobs_concurrency_cancel", {"cancelled": False, "payload": "compile"}),
    TStage("t.casulo.universes", "semantic_routing_lifecycle", {"hot_count": 2, "max_hot": 3, "route_allowed": True}),
    TStage("t.casulo.simulation", "simulation_acceptance", {"sandboxed": True}, ("simulation",)),
    TStage("t.casulo.materialization", "publish_commit", {"approved": True}, ("manifest",)),
    TStage("t.casulo.dialogue", "interface_state", {"progress_event_real": True}),
    TStage("t.casulo.receipts", "recovery_update", {"chain_valid": True}),
)


@dataclass(frozen=True, slots=True)
class TStandardLibraryRun:
    status: str
    final_value: str | None
    stages: tuple[dict[str, Any], ...]
    tcap_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.t-stdlib-run/2.0",
            "status": self.status,
            "final_value": self.final_value,
            "tcap_hash": self.tcap_hash,
            "stages": list(self.stages),
        }


class ProductiveTStandardLibrary:
    """Sequential host for T decisions; it transports but never recomputes them."""

    def __init__(self, runtime: str | Path) -> None:
        self.runtime = Path(runtime).resolve()
        if not self.runtime.is_file():
            raise TStandardLibraryError("runtime T produtivo ausente")

    def run(
        self,
        tcap: str | Path,
        scratch: str | Path,
        *,
        scope_id: str = "stdlib:vertical-slice",
        stages: tuple[TStage, ...] = STAGES,
    ) -> TStandardLibraryRun:
        root, manifest, typed = verify_tcap_v2(tcap)
        modules = {item["module"]: item for item in typed["modules"]}
        target = Path(scratch).resolve()
        if target.exists() and any(target.iterdir()):
            raise TStandardLibraryError("scratch precisa estar vazio")
        target.mkdir(parents=True, exist_ok=True)
        previous_value: str | None = None
        previous_receipt = "0" * 64
        observed: list[dict[str, Any]] = []
        for index, stage in enumerate(stages, 1):
            if stage.module not in modules:
                raise TStandardLibraryError(f"módulo T ausente: {stage.module}")
            payload = dict(stage.fixed_input)
            if index > 1:
                payload["previous"] = previous_value
            input_path = target / f"{index:02d}-{stage.module.replace('.', '-')}.json"
            input_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
                encoding="utf-8", newline="\n",
            )
            completed = subprocess.run(
                [
                    str(self.runtime), str(root), f"{stage.module}::decide", str(input_path),
                    ",".join(stage.grants), stage.surface_id, scope_id, previous_receipt,
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15, check=False,
            )
            if completed.returncode != 0:
                raise TStandardLibraryError(f"runtime T falhou em {stage.module}: {completed.stderr.strip()}")
            execution = json.loads(completed.stdout)
            observable = execution["observable"]
            receipt = execution["runtime_receipt"]
            self._validate_receipt(
                receipt, observable, payload, stage=stage, module_ir=modules[stage.module],
                tcap_hash=manifest["tcap_hash"], previous_receipt=previous_receipt,
            )
            result = observable["result"]
            observed.append({
                "index": index, "module": stage.module, "surface_id": stage.surface_id,
                "input": payload, "observable": observable, "receipt": receipt,
            })
            previous_receipt = receipt["receipt_hash"]
            if result.get("kind") != "ok":
                return TStandardLibraryRun("BLOCKED", None, tuple(observed), manifest["tcap_hash"])
            previous_value = result.get("value")
        return TStandardLibraryRun("PASS", previous_value, tuple(observed), manifest["tcap_hash"])

    @staticmethod
    def _validate_receipt(
        receipt: Mapping[str, Any], observable: Mapping[str, Any], payload: Mapping[str, Any],
        *, stage: TStage, module_ir: Mapping[str, Any], tcap_hash: str, previous_receipt: str,
    ) -> None:
        required = {
            "schema", "decision_id", "surface_id", "scope_id", "t_source_hash", "t_ir_hash",
            "tcap_hash", "runtime_function", "canonical_input_hash", "canonical_output_hash",
            "effects_requested", "grants_consumed", "foreign_calls", "result",
            "previous_receipt_hash", "monotonic_timestamp_ns", "runtime_id", "receipt_hash",
        }
        if set(receipt) != required or receipt.get("schema") != "casulo.t-decision-receipt/2.0":
            raise TStandardLibraryError("receipt T incompleto")
        checks = {
            "runtime": receipt["runtime_id"] == "t-runtime/rust-2.0",
            "function": receipt["runtime_function"] == f"{stage.module}::decide",
            "surface": receipt["surface_id"] == stage.surface_id,
            "tcap": receipt["tcap_hash"] == tcap_hash,
            "ir": receipt["t_ir_hash"] == canonical_sha256(module_ir),
            "input": receipt["canonical_input_hash"] == canonical_sha256(payload),
            "output": receipt["canonical_output_hash"] == canonical_sha256(observable),
            "previous": receipt["previous_receipt_hash"] == previous_receipt,
            "effects": receipt["effects_requested"] == list(stage.grants),
            "grants": receipt["grants_consumed"] == list(stage.grants),
            "foreign": receipt["foreign_calls"] == [],
        }
        seed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        checks["hash"] = receipt["receipt_hash"] == canonical_sha256(seed)
        if not all(checks.values()):
            failed = [key for key, value in checks.items() if not value]
            raise TStandardLibraryError(f"receipt T causal inválido: {failed}")
