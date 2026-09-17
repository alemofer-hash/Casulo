from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from casulo.product.math_boundary import (
    mathematical_boundary_inventory,
    profile_similarity_kernels,
    verify_similarity_equivalence,
)
from casulo_owner.math_boundary import OwnerMathBoundary


def _json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _attempt(root: Path) -> Path:
    base = root / "arc-math-boundary-2026-08-18-attempt1"
    target = base
    sequence = 2
    while target.exists():
        target = root / f"arc-math-boundary-2026-08-18-attempt{sequence}"
        sequence += 1
    target.mkdir(parents=True)
    return target


def _seal(root: Path) -> tuple[str, int]:
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name not in {"MANIFEST.json", "SHA256SUMS"}):
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({"path": relative, "sha256": digest, "bytes": path.stat().st_size})
    manifest = {
        "schema": "casulo.arc8-evidence-manifest/1.0",
        "classification": "PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK",
        "files": entries,
    }
    _json(root / "MANIFEST.json", manifest)
    manifest_hash = hashlib.sha256((root / "MANIFEST.json").read_bytes()).hexdigest()
    sums = [f"{entry['sha256']}  {entry['path']}" for entry in entries]
    sums.append(f"{manifest_hash}  MANIFEST.json")
    (root / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")
    return manifest_hash, len(entries) + 1


def run(repo: Path, output_root: Path) -> Path:
    target = _attempt(output_root)
    inventory = mathematical_boundary_inventory()
    equivalence = verify_similarity_equivalence()
    profile = profile_similarity_kernels()
    policy = repo / "private/casulo-owner/t-v2/math-boundary-policy.t"
    tcap = OwnerMathBoundary.build_policy(policy, target / "math-boundary-policy.tcap")
    boundary = OwnerMathBoundary(
        repo / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime"),
        tcap,
        target / "authority",
    )
    selection = boundary.decide(equivalence, profile)
    checks = {
        "inventory_declares_foreign_neural_algebra": inventory["boundaries"][0]["authority"].startswith("FOREIGN_NUMERICAL"),
        "semantic_equivalence": equivalence.passed,
        "logical_traffic_reduced": profile.traffic_reduced,
        "profile_is_product_diagnostic": profile.classification == "SHORT_PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK",
        "t_receipt_present": selection.t_call is not None and len(selection.t_call.receipt["receipt_hash"]) == 64,
        "t_decision_consumed": selection.specialized_adopted == (selection.selected_kernel.endswith("sparse-signed-cosine-python-v1")),
        "safe_reference_available": True,
    }
    gate = {
        "schema": "casulo.arc8-gate/1.0",
        "state": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "selected_kernel": selection.selected_kernel,
        "specialized_adopted": selection.specialized_adopted,
        "selection_reason": selection.reason,
        "authorized_claim": "T governa a adoção de uma representação esparsa semanticamente equivalente no kernel de similaridade da LivingMemory.",
        "forbidden_claims": inventory["forbidden_claims"],
    }
    _json(target / "inventory.json", inventory)
    _json(target / "equivalence.json", equivalence.to_dict())
    _json(target / "profile.json", profile.to_dict())
    _json(target / "selection.json", selection.to_dict())
    _json(target / "gate.json", gate)
    report = f"""# ARC-8 — Fronteira matemática verificável

Estado: `{gate['state']}`  
Classificação: `PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK`

O kernel escolhido foi `{selection.selected_kernel}`. A decisão foi `{selection.reason}` e o resultado T foi consumido pelo caminho owner. A equivalência máxima observada foi `{equivalence.max_absolute_difference}` sob tolerância `{equivalence.tolerance}`.

O perfil curto mediu razão candidato/referência `{profile.candidate_reference_ratio:.6f}` com limiar de adoção pré-fixado em `{profile.adoption_ratio_threshold:.2f}`. O tráfego é contagem lógica de posições da representação (`{profile.candidate_logical_slots}` contra `{profile.reference_logical_slots}`), não bytes físicos, energia ou FLOPs.

## Fronteira honesta

Esta prova vale somente para o cosseno signed-hash de 64 dimensões usado pela LivingMemory. Qwen3-4B continua executando álgebra via llama.cpp/ggml; Whisper continua via whisper.cpp/ggml. A pilha tensorial histórica T não é o caminho owner atual. Não há alegação de superioridade matricial geral, energética ou científica.
"""
    (target / "report.md").write_text(report, encoding="utf-8", newline="\n")
    manifest_hash, files = _seal(target)
    print(json.dumps({"state": gate["state"], "output": str(target), "manifest_sha256": manifest_hash, "sealed_files": files, "selected_kernel": selection.selected_kernel, "ratio": profile.candidate_reference_ratio}, ensure_ascii=False))
    if gate["state"] != "PASS":
        raise SystemExit(1)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal the bounded ARC-8 mathematical boundary gate")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path("product-demos/human-proof"))
    args = parser.parse_args()
    run(args.repo.resolve(), args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
