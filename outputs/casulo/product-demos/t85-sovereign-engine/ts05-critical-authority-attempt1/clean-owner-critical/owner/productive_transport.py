from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .authority import canonical_sha256
from .v2_tcap import verify_tcap_v2


_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


class ProductiveTError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProductiveTCall:
    module: str
    function: str
    observable: Mapping[str, Any]
    receipt: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.observable.get("result", {}).get("kind") == "ok"


class ProductiveTExecutor:
    """Exact-process adapter for T; validation is allowed, recomputation is not."""

    def __init__(self, runtime: str | Path, tcap: str | Path, scratch: str | Path) -> None:
        self.runtime = Path(runtime).resolve()
        if not self.runtime.is_file():
            raise ProductiveTError("runtime T produtivo ausente")
        self.root, self.manifest, typed = verify_tcap_v2(tcap)
        self.modules = {item["module"]: item for item in typed["modules"]}
        self.sources = {item["module"]: item["sha256"] for item in self.manifest["sources"]}
        self.scratch = Path(scratch).resolve()
        self.scratch.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        module: str,
        function: str,
        payload: Mapping[str, Any],
        *,
        call_id: str,
        surface_id: str,
        scope_id: str,
        grants: tuple[str, ...] = (),
        previous_receipt_hash: str = "0" * 64,
    ) -> ProductiveTCall:
        for label, value in (("call_id", call_id), ("surface_id", surface_id), ("scope_id", scope_id)):
            if not _SAFE_ID.fullmatch(value):
                raise ProductiveTError(f"{label} inválido")
        if module not in self.modules or module not in self.sources:
            raise ProductiveTError("módulo T ausente")
        if function not in {item["name"] for item in self.modules[module]["functions"]}:
            raise ProductiveTError("função T ausente")
        input_path = (self.scratch / f"{call_id}.json").resolve()
        if not input_path.is_relative_to(self.scratch) or input_path.exists():
            raise ProductiveTError("input T duplicado ou fora do scratch")
        canonical_input = dict(payload)
        input_path.write_text(
            json.dumps(canonical_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
        completed = subprocess.run(
            [
                str(self.runtime), str(self.root), f"{module}::{function}", str(input_path),
                ",".join(sorted(set(grants))), surface_id, scope_id, previous_receipt_hash,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, check=False,
        )
        if completed.returncode != 0:
            raise ProductiveTError(f"runtime T falhou fechado: {completed.stderr.strip()}")
        try:
            document = json.loads(completed.stdout)
            observable = document["observable"]
            receipt = document["runtime_receipt"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ProductiveTError("runtime T retornou envelope inválido") from error
        self._validate(
            module, function, canonical_input, observable, receipt,
            surface_id=surface_id, scope_id=scope_id, grants=grants,
            previous_receipt_hash=previous_receipt_hash,
        )
        return ProductiveTCall(module, function, observable, receipt)

    def _validate(
        self,
        module: str,
        function: str,
        payload: Mapping[str, Any],
        observable: Mapping[str, Any],
        receipt: Mapping[str, Any],
        *,
        surface_id: str,
        scope_id: str,
        grants: tuple[str, ...],
        previous_receipt_hash: str,
    ) -> None:
        required = {
            "schema", "decision_id", "surface_id", "scope_id", "t_source_hash", "t_ir_hash",
            "tcap_hash", "runtime_function", "canonical_input_hash", "canonical_output_hash",
            "effects_requested", "grants_consumed", "foreign_calls", "result",
            "previous_receipt_hash", "monotonic_timestamp_ns", "runtime_id", "receipt_hash",
        }
        requested = receipt.get("effects_requested", [])
        checks = {
            "schema": set(receipt) == required and receipt.get("schema") == "casulo.t-decision-receipt/2.0",
            "runtime": receipt.get("runtime_id") == "t-runtime/rust-2.0",
            "function": receipt.get("runtime_function") == f"{module}::{function}",
            "surface": receipt.get("surface_id") == surface_id,
            "scope": receipt.get("scope_id") == scope_id,
            "source": receipt.get("t_source_hash") == self.sources[module],
            "ir": receipt.get("t_ir_hash") == canonical_sha256(self.modules[module]),
            "tcap": receipt.get("tcap_hash") == self.manifest["tcap_hash"],
            "input": receipt.get("canonical_input_hash") == canonical_sha256(payload),
            "output": receipt.get("canonical_output_hash") == canonical_sha256(observable),
            "previous": receipt.get("previous_receipt_hash") == previous_receipt_hash,
            "grants": receipt.get("grants_consumed") == [item for item in requested if item in set(grants)],
            "foreign": receipt.get("foreign_calls") == [],
            "result": receipt.get("result") == observable.get("result", {}).get("kind"),
        }
        seed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        checks["hash"] = receipt.get("receipt_hash") == canonical_sha256(seed)
        if not all(checks.values()):
            raise ProductiveTError(f"receipt causal inválido: {[key for key, value in checks.items() if not value]}")
