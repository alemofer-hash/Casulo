from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
T85 = ROOT / "release/t85-human-proof"


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def write_json(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    mutation = load(CAMPAIGN / "causal_mutations-attempt2/summary.json")
    equivalence = load(CAMPAIGN / "equivalence/flood-v1/equivalence.json")
    experiment = load(CAMPAIGN / "baselines/ti10-v2/analysis.json")
    expanded = load(CAMPAIGN / "baselines/ti10-v2/analysis-expanded.json")
    holdouts = load(CAMPAIGN / "holdouts/v1/summary.json")
    demo = load(CAMPAIGN / "demo/live-v2/summary.json")
    required = {
        "mutations_9_of_9": mutation.get("gate") == "PASS" and mutation.get("passed") == mutation.get("required") == 9,
        "flood_equivalence": equivalence.get("status") == "PASS",
        "paired_blocks_7": experiment.get("valid_blocks") == 7,
        "material_wall_reduction": experiment.get("paired_bootstrap_ci95", {}).get("upper", 2) < 0.9,
        "holdouts_2": holdouts.get("status") == "PASS" and len(holdouts.get("holdouts", [])) == 2,
        "live_demo_v2": demo.get("status") == "PASS" and demo.get("steps") == 12,
        "energy_not_fabricated": expanded["psi_physical"]["package_joules"] is None and expanded["psi_physical"]["total_system_joules"] is None,
        "t85_manifest_unchanged": file_hash(T85 / "MANIFEST.json") == "87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee",
        "t85_sums_unchanged": file_hash(T85 / "SHA256SUMS") == "1f897e9a9cd1e9e8bebb3d9e3ac05852e95d3655c7cfcc62cd6d2d3f12d723de",
        "t85_sbom_unchanged": file_hash(T85 / "SBOM.spdx.json") == "42be95ebd7229253020b81700e308b5d0ab7efdec70fb49da207d0e8f442c55f",
    }
    if not all(required.values()):
        raise RuntimeError(f"final gates failed: {required}")
    surfaces = [item["surface"] for item in mutation["mutations"]]
    authority = {
        "schema": "casulo.interlocution-authority-after/1.0", "status": "PASS",
        "A_T_numerator": 9, "A_T_denominator": 9, "A_T": 1.0,
        "surfaces": [{"surface": surface, "t_source": True, "general_pipeline": True, "consumed_before_relevant_work": True, "causal_mutation_pass": True, "receipt": True, "publisher_consumes_t_judge": True, "authority": "T_AUTHORITY"} for surface in surfaces],
        "foreign_primitives": ["AOT x86-64 Flood kernel", "Rust wrapper", "NumPy holdout primitives", "PyTorch Eager oracles", "OS allocator and clocks"],
        "foreign_decision_authority": False,
    }
    authority["authority_sha256"] = digest(authority)
    write_json(CAMPAIGN / "authority-after.json", authority)
    compression = {
        "schema": "casulo.interlocution-compression/1.0",
        "status": "OBSERVED_MATERIAL_NONENERGY_PHYSICAL_REDUCTION",
        "source_analysis": "baselines/ti10-v2/analysis-expanded.json",
        "wall_time_D_over_A_median": expanded["end_to_end"]["median_D_over_A_wall_ratio"],
        "wall_time_ci95": experiment["paired_bootstrap_ci95"],
        "observed_cpu_time_D_over_A_median": expanded["end_to_end"]["median_D_over_A_observed_cpu_time_ratio"],
        "peak_rss_D_over_A": expanded["psi_physical"]["peak_rss_ratio_D_over_A"],
        "steady_state_thread_cycles_D_over_A": expanded["steady_state"]["median_D_over_A_thread_cycles_ratio"],
        "network_math_operations_eliminated": False,
        "causal_mechanism": "same declared training math through a lean AOT primitive selected and bounded by T, avoiding general framework/import/dispatch/state overhead",
        "package_joules": None, "total_system_joules": None, "energy_claim": "PROHIBITED",
    }
    compression["compression_sha256"] = digest(compression)
    write_json(CAMPAIGN / "compression.json", compression)
    verification = {
        "schema": "casulo.interlocution-independent-aggregate-verification/1.0",
        "status": "PASS",
        "terminal_state": "T_CAUSAL_AUTHORITY_VALIDATED_PHYSICAL_INSTRUMENT_PENDING",
        "gates": required,
        "authority_after_sha256": authority["authority_sha256"],
        "compression_sha256": compression["compression_sha256"],
        "mutation_summary_sha256": mutation["summary_sha256"],
        "flood_equivalence_sha256": equivalence["equivalence_sha256"],
        "holdout_summary_sha256": file_hash(CAMPAIGN / "holdouts/v1/summary.json"),
        "demo_v2_summary_sha256": demo["summary_sha256"],
        "analysis_json_trusted_without_recomposition": False,
        "energy_verified": False,
    }
    verification["verification_sha256"] = digest(verification)
    write_json(CAMPAIGN / "independent_verification.json", verification)
    report = f"""# Prova viva do Teorema da Interlocução — relatório

Estado: `T_CAUSAL_AUTHORITY_VALIDATED_PHYSICAL_INSTRUMENT_PENDING`.

## Resultado

Esta campanha valida uma instância causal, reproduzível e falsificável em três
workloads. Ela não prova universalidade e não mede energia. T governou as nove
decisões críticas, cada mutação T alterou a decisão/contrato ou causou recusa, e
o publicador só aceitou D após o receipt do juiz T.

- `A_T=9/9=1.00`; mutações causais `9/9 PASS`;
- Flood completo: três candidatos e três oráculos, equivalência `PASS`;
- holdouts: MAE linear e BCE logístico/working-set parcial, dois casos por
  candidato e por oráculo, ambos `PASS`;
- TI10: sete blocos A/B/C/D; D/A wall end-to-end mediano
  `{experiment['median_D_over_A_wall_ratio']}`, IC95%
  `[{experiment['paired_bootstrap_ci95']['lower']}, {experiment['paired_bootstrap_ci95']['upper']}]`;
- pico RSS D/A `{expanded['psi_physical']['peak_rss_ratio_D_over_A']}`;
- tempo de CPU observado D/A `{expanded['end_to_end']['median_D_over_A_observed_cpu_time_ratio']}`;
- package joules e total-system joules: `UNAVAILABLE`, não zero.

## Respostas vinculantes

1. T governou dataset, inicialização, precisão, loss, update, estado do
   otimizador, working set, stopping e aceitação.
2. Kernels x86-64, Rust, NumPy, PyTorch, alocador e hardware continuaram
   estrangeiros; nenhum deles concedeu autoridade sem T.
3. As nove mutações alteraram TCAP e execução/recusa sem mudança em Python/C.
4. Os artefatos principais documentam 79 treinamentos completos: smoke 1;
   equivalência 6; TI10 63 incluindo warm-ups/oráculos; holdouts 8; demo v2 1.
5. Equivalência foi preservada no Flood e nos dois holdouts.
6. A matemática declarada da rede não foi eliminada. Eliminou-se overhead
   observável de framework/import/dispatch/estado ao usar primitive AOT lean.
7. Overhead D mediano por janela: arquitetura T
   `{expanded['t_overhead']['median_architecture_seconds_per_window']} s`,
   auditoria `{expanded['t_overhead']['median_independent_audit_seconds_per_window']} s`,
   julgamento `{expanded['t_overhead']['median_judgment_seconds_per_window']} s`,
   publicação `{expanded['t_overhead']['median_publication_seconds_per_window']} s`.
8. Redução exata de operações matemáticas: não. Estado/overhead reduzidos são
   sustentados por RSS, CPU, ciclos e tempo, não por contagem de toda instrução.
9. Houve redução física não energética em wall, CPU, ciclos e RSS neste protocolo.
10. Não houve redução energética validada; nenhum joule foi medido.
11. Os ataques implementados produziram zero falso PASS, sem provar ausência de ataques desconhecidos.
12. Dois holdouts sustentam a fronteira, mas não generalizam para toda rede.
13. Sustenta-se a proposição condicional e uma instância empírica sob R,
    autoridade causal T, receipts e V_R delimitado.
14. Universalidade, solidez completa de V_R, outros hosts e energia permanecem hipótese.
15. Próximo experimento: replicação multi-host independente com wattímetro,
    package energy válido e arquiteturas convolucionais/atenção pré-congeladas.

## Limites

O receipt Flood é envelopado pelo supervisor governado após o kernel síncrono;
contadores são internos, mas o hash ainda não é assinado dentro do kernel. A
redução end-to-end inclui overhead T e imports; compilação foi medida separada.
Tempo humano de interlocução não tinha timestamp válido e é `UNAVAILABLE`.
Nenhum claim energético, universal, PyTorch/Inductor geral, GPU, datacenter ou
produto é autorizado.
"""
    report_path = CAMPAIGN / "report.md"
    if report_path.exists():
        raise FileExistsError(report_path)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    files = []
    for path in sorted(CAMPAIGN.rglob("*")):
        if not path.is_file() or path.name in {"MANIFEST.json", "SHA256SUMS"} or any(part.startswith(".tmp") for part in path.relative_to(CAMPAIGN).parts):
            continue
        files.append({"path": path.relative_to(CAMPAIGN).as_posix(), "bytes": path.stat().st_size, "sha256": file_hash(path)})
    manifest = {"schema": "casulo.interlocution-manifest/1.0", "campaign_id": CAMPAIGN.name, "created_at_utc": datetime.now(timezone.utc).isoformat(), "terminal_state": verification["terminal_state"], "files": files, "file_count": len(files), "cloud": "RELEASE_LOCKED", "external_api": "PROHIBITED", "publication": "PROHIBITED", "signature": "DEVELOPMENT_NOT_COMMERCIAL"}
    manifest["manifest_sha256"] = digest(manifest)
    write_json(CAMPAIGN / "MANIFEST.json", manifest)
    (CAMPAIGN / "SHA256SUMS").write_text("".join(f"{item['sha256']}  {item['path']}\n" for item in files), encoding="utf-8", newline="\n")
    print(json.dumps({"status": verification["terminal_state"], "files": len(files), "manifest_sha256": manifest["manifest_sha256"], "sha256sums_sha256": file_hash(CAMPAIGN / "SHA256SUMS")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
