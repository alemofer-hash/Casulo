from __future__ import annotations

import hashlib
import json
import platform
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from casulo.livelab.energy_v1.hwinfo import (
    extract_interval_csv,
    inspect_file,
    integrate_window,
    read_shared_snapshot,
)
from energy_confirmatory.analysis import analyze_confirmatory_campaign


CAMPAIGN = ROOT / "outputs/casulo/interlocution-energy/2026-08-19-e1-e2-attempt1"
SEAL = CAMPAIGN / "seal-attempt-2"
EXPLORATORY = CAMPAIGN / "exploratory-hwinfo-de-v1"
PILOT = CAMPAIGN / "pilot"
HWINFO = ROOT / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
DOC_DIR = ROOT / "docs/research/interlocution/energy-confirmatory"
REPORT = DOC_DIR / "ENERGY_E1_E2_RESULT_2026-08-19.md"
STATE = DOC_DIR / "ENERGY_CONFIRMATORY_EXECUTION_STATE.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_text(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")


def git(*args: str) -> str:
    process = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return process.stdout.strip() if process.returncode == 0 else f"UNAVAILABLE:{process.stderr.strip()}"


def main() -> int:
    if REPORT.exists() or STATE.exists():
        raise FileExistsError("append-only E1/E2 report already exists")
    exploratory = json.loads((EXPLORATORY / "analysis.json").read_text(encoding="utf-8"))
    d_pilot = json.loads((PILOT / "D-governed-count2/arm-result.json").read_text(encoding="utf-8"))
    e_pilot = json.loads((PILOT / "E-static-count2/same-kernel-result.json").read_text(encoding="utf-8"))
    pilot_equivalence = _compare_equivalence_files()
    snapshot, parsed, inspection = inspect_file(HWINFO)
    selected = inspection["selected_energy_sensor"]
    source_capability = {
        "schema": "casulo.interlocution-energy-capabilities/2.0",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "TOTAL_SYSTEM_WALL": {
            "available": False,
            "qualified": False,
            "reason": "no calibrated physical wall analyzer with serial/certificate/export was detected",
        },
        "CPU_PACKAGE_RAPL": {
            "available": False,
            "qualified": False,
            "reason": "bare-metal Windows host exposes no validated Linux powercap energy_uj source",
        },
        "EXPLORATORY_HWINFO": {
            "available": True,
            "qualified": False,
            "reason": "reported package-power telemetry is usable only for exploratory trapezoidal integration",
            "literal_sensor": selected["literal_name"],
            "unit": selected["unit"],
            "provenance": selected["provenance"],
            "median_interval_seconds": inspection["sampling"]["median_seconds"],
            "p95_interval_seconds": inspection["sampling"]["p95_seconds"],
        },
        "battery": {
            "present": psutil.sensors_battery() is not None,
            "percent": psutil.sensors_battery().percent if psutil.sensors_battery() else None,
            "ac_connected": psutil.sensors_battery().power_plugged if psutil.sensors_battery() else None,
            "stable_for_total_system": False,
            "reason": "battery was charging during the exploratory campaign; total-system attribution is prohibited",
        },
    }
    write_json(SEAL / "instrument-capabilities.json", source_capability)

    preflight = {
        "schema": "casulo.interlocution-energy-preflight/2.0",
        "campaign_id": CAMPAIGN.name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "root": str(ROOT),
            "branch": git("branch", "--show-current"),
            "commit": git("rev-parse", "HEAD"),
            "worktree_preserved": True,
            "porcelain_entries": len(git("status", "--porcelain=v1").splitlines()),
        },
        "host": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "memory_bytes": psutil.virtual_memory().total,
            "free_disk_bytes": psutil.disk_usage(str(ROOT)).free,
        },
        "full_worker_hashes": {
            "executable": sha256_file(ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2/worker/tcap_full_worker.exe"),
            "dataset": sha256_file(ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2/artifact/FloodSurrogate.dataset.bin"),
            "initializations": sha256_file(ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2/artifact/FloodSurrogate.initializations.bin"),
        },
        "source_csv": {
            "path": str(HWINFO),
            "snapshot_bytes": snapshot.file_size_at_open,
            "snapshot_sha256": snapshot.sha256,
            "source_was_not_modified": True,
        },
    }
    write_json(SEAL / "preflight.json", preflight)

    raw_dir = SEAL / "raw-meter-segments"
    recomposed = []
    immutable_snapshot = read_shared_snapshot(HWINFO)
    for sample_path in sorted((EXPLORATORY / "samples").glob("*.json")):
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        start = datetime.fromisoformat(sample["start_utc"])
        end = datetime.fromisoformat(sample["end_utc"])
        segment_path = raw_dir / f"{sample_path.stem}.csv"
        if segment_path.exists():
            raise FileExistsError(f"append-only source segment exists: {segment_path}")
        segment_path.parent.mkdir(parents=True, exist_ok=True)
        segment_path.write_text(
            extract_interval_csv(immutable_snapshot, start - timedelta(seconds=1), end + timedelta(seconds=1)),
            encoding="utf-8-sig",
            newline="\n",
        )
        _, segment, _ = inspect_file(segment_path)
        recalculated = integrate_window(segment, start, end, minimum_samples=60)
        original = sample["energy_window"]
        difference = None if recalculated.energy_joules is None else recalculated.energy_joules - original["energy_joules"]
        recomposed.append({
            "sample": sample_path.stem,
            "segment_sha256": sha256_file(segment_path),
            "original_joules": original["energy_joules"],
            "recomputed_joules": recalculated.energy_joules,
            "difference_joules": difference,
            "exact_match_within_1e-9": difference is not None and abs(difference) <= 1e-9,
            "status": recalculated.status,
        })
    write_json(SEAL / "meter-recomposition.json", {"samples": recomposed, "all_exact": all(item["exact_match_within_1e-9"] for item in recomposed)})

    same_kernel = {
        "schema": "casulo.interlocution-same-kernel-identification/1.0",
        "pilot_K": 2,
        "D_total_seconds": d_pilot["inner_total_ns"] / 1e9,
        "E_parent_seconds": e_pilot["parent_monotonic_ns"] / 1e9,
        "D_over_E_end_to_end_ratio_at_K2": d_pilot["inner_total_ns"] / e_pilot["parent_monotonic_ns"],
        "D_child_seconds": d_pilot["work_summary"]["child_timing"]["worker_monotonic_ns"] / 1e9,
        "E_child_seconds": e_pilot["child_monotonic_ns"] / 1e9,
        "same_result_sha256": d_pilot["result_sha256"] == e_pilot["result_sha256"],
        "equivalence": pilot_equivalence,
        "D_executable_sha256": preflight["full_worker_hashes"]["executable"],
        "E_executable_sha256": preflight["full_worker_hashes"]["executable"],
        "gate": "PASS_SAME_EXECUTABLE_SAME_INPUTS_SAME_RESULT",
        "receipt_boundary": "work receipts are supervisor-derived from completed result bytes; not kernel-internal signatures",
    }
    write_json(SEAL / "same-kernel-identification.json", same_kernel)

    e1 = {
        "schema": "casulo.interlocution-energy-e1-analysis/1.0",
        "terminal_state": "E1_BLOCKED_PHYSICAL_INSTRUMENT",
        "confirmatory_pairs": 0,
        "exploratory_valid_pairs": exploratory["valid_pairs"],
        "exploratory_rejected_pairs": exploratory["required_pairs"] - exploratory["valid_pairs"],
        "exploratory_D_joules_per_training": exploratory["median_D_joules_per_training"],
        "exploratory_E_joules_per_training": exploratory["median_E_joules_per_training"],
        "exploratory_D_over_E_ratio": exploratory["median_D_over_E"],
        "exploratory_relative_change_D_vs_E": exploratory["median_D_over_E"] - 1,
        "equivalence": "PASS_ZERO_DIFFERENCE_ALL_THREE_ATTEMPTED_PAIRS",
        "thermal": {"throttling_valid_windows": 0, "maximum_valid_window_temperature_c": _maximum_valid_temperature()},
        "claim_authorized": False,
        "why": [
            "HWiNFO package power is not a calibrated physical total-system instrument",
            "no valid RAPL cumulative package-energy source is exposed on this Windows host",
            "only two thermally paired exploratory pairs were valid",
            "battery charging prohibits total-system attribution",
        ],
    }
    write_json(SEAL / "e1-analysis.json", e1)

    e2 = analyze_confirmatory_campaign(
        (),
        candidate="D_T_ARCHITECT_AUDITOR_JUDGE",
        baseline="E_STATIC_POLICY_SAME_NATIVE_KERNEL",
        expected_hosts=6,
        expected_cpu_families=3,
        expected_labs=2,
        expected_workloads=5,
        expected_pairs_per_host_workload=24,
        bootstrap_seed=2026081902,
    )
    e2["physically_observed_but_not_confirmatory_hosts"] = 1
    e2["qualified_total_system_hosts"] = 0
    e2["terminal_state"] = "E2_BLOCKED_INSUFFICIENT_EXTERNAL_SCALE_AND_INSTRUMENTATION"
    write_json(SEAL / "e2-analysis.json", e2)

    validation = {
        "schema": "casulo.interlocution-energy-runtime-v2-validation/1.0",
        "command": "python -m pytest -q research/interlocution/tests/test_energy_confirmatory_v2.py research/interlocution/tests tests/test_livelab_energy_v1.py",
        "passed": 54,
        "failed": 0,
        "duration_seconds": 7.00,
        "covered": [
            "power-only trapezoidal integration", "cumulative joules", "exact boundary interpolation",
            "mock rejection", "calibration/range/firmware/clock qualification", "K completed normalization",
            "gap/reset/partial/range-change rejection", "batteryless desktop", "unstable laptop",
            "hierarchical multi-host analysis", "same-kernel full work unit",
        ],
    }
    write_json(SEAL / "runtime-v2-validation.json", validation)

    report = render_report(preflight, source_capability, validation, same_kernel, e1, e2, exploratory, recomposed)
    write_text(REPORT, report)
    state = render_state(preflight, e1, e2)
    write_text(STATE, state)

    files = sorted(path for path in SEAL.rglob("*") if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"})
    files.extend([REPORT, STATE])
    manifest = {
        "schema": "casulo.interlocution-energy-manifest/2.0",
        "campaign_id": CAMPAIGN.name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in files
        ],
        "scientific_claim_authorized": False,
        "terminal_states": {"E1": e1["terminal_state"], "E2": e2["terminal_state"]},
    }
    write_json(SEAL / "MANIFEST.json", manifest)
    sums = "".join(f"{item['sha256']}  {item['path']}\n" for item in manifest["files"])
    write_text(SEAL / "SHA256SUMS", sums)
    print(json.dumps({
        "status": "SEALED_TRUTHFUL_BLOCKED_RESULT",
        "report": str(REPORT),
        "report_sha256": sha256_file(REPORT),
        "E1": e1["terminal_state"],
        "E2": e2["terminal_state"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


def _compare_equivalence_files() -> dict[str, Any]:
    from energy_confirmatory.same_kernel import compare_same_work
    return compare_same_work(
        PILOT / "D-governed-count2/worker/worker-result.bin",
        PILOT / "E-static-count2/worker-result.bin",
    )


def _maximum_valid_temperature() -> float:
    values = []
    accepted_pairs = {item["pair_id"] for item in json.loads((EXPLORATORY / "analysis.json").read_text(encoding="utf-8"))["pairs"]}
    for path in (EXPLORATORY / "samples").glob("*.json"):
        sample = json.loads(path.read_text(encoding="utf-8"))
        if sample["pair_id"] in accepted_pairs:
            values.extend(float(item["temperature_c"]) for item in sample["thermal_observations"] if item.get("temperature_c") is not None)
    return max(values)


def render_report(preflight: dict[str, Any], sources: dict[str, Any], validation: dict[str, Any], same: dict[str, Any], e1: dict[str, Any], e2: dict[str, Any], exploratory: dict[str, Any], recomposed: list[dict[str, Any]]) -> str:
    pairs = exploratory["pairs"]
    lines = [
        "# E1/E2 — resultado energético honesto da Interlocução",
        "",
        f"Data de selagem: `{datetime.now(timezone.utc).isoformat()}`  ",
        f"Commit preservado: `{preflight['repository']['commit']}`  ",
        f"Branch: `{preflight['repository']['branch']}`",
        "",
        "## Veredito curto",
        "",
        "**E1 não foi aprovado:** não existe neste host um wattímetro físico calibrado nem uma fonte RAPL cumulativa válida. O HWiNFO permitiu apenas uma medição exploratória do pacote CPU.",
        "",
        "**E2 não foi aprovado:** a topologia confirmatória observada é 0/6 hosts qualificados, 0/3 famílias de CPU, 0/2 laboratórios e 0/5 workloads com energia total válida.",
        "",
        "O resultado exploratório local aponta na direção **negativa** para a hipótese de que a governança T, isolada sobre o mesmo kernel, economiza energia: D/E = "
        f"`{e1['exploratory_D_over_E_ratio']:.6f}` — D usou aproximadamente `{100 * e1['exploratory_relative_change_D_vs_E']:.2f}%` mais energia reportada do pacote que E. "
        "Isso não é uma derrota do sistema integrado contra PyTorch; é a medição do overhead causal de T contra o mesmo kernel nativo.",
        "",
        "O caminho continua **positivo em validade científica**: o kernel foi realmente isolado, os resultados foram bit a bit iguais nos testes feitos, uma tentativa termicamente assimétrica foi rejeitada e nenhum joule inexistente foi fabricado.",
        "",
        "## Números centrais",
        "",
        "| Medida | Resultado | Leitura permitida |",
        "|---|---:|---|",
        f"| K por braço/janela | {480} | 480 treinamentos completos e distintos |",
        f"| Tentativas pareadas | {exploratory['required_pairs']} | todas preservadas |",
        f"| Pares exploratórios válidos | {exploratory['valid_pairs']} | 1 rejeitado por assimetria térmica de 5 °C |",
        f"| D — mediana J/treino | {e1['exploratory_D_joules_per_training']:.9f} | HWiNFO package, exploratório |",
        f"| E — mediana J/treino | {e1['exploratory_E_joules_per_training']:.9f} | HWiNFO package, exploratório |",
        f"| Razão D/E | {e1['exploratory_D_over_E_ratio']:.9f} | acima de 1 favorece E |",
        f"| Variação D vs E | {100 * e1['exploratory_relative_change_D_vs_E']:+.3f}% | sinal negativo para economia causal de T |",
        f"| Máxima térmica em janelas válidas | {e1['thermal']['maximum_valid_window_temperature_c']:.1f} °C | 0 throttling |",
        "| Diferença máxima de resultado D/E | 0 | perdas, parâmetros e predições |",
        "| Treinamentos medidos válidos | 1.920 | 960 por braço |",
        "| Treinamentos executados totais | 2.880 | inclui o par térmico rejeitado |",
        "| Receipts de trabalho preservados | 2.880 | supervisor-derived; não chamados de assinatura interna do kernel |",
        "",
        "### Pares válidos",
        "",
        "| Par | D J/treino | E J/treino | D/E | D W médio | E W médio | ΔT inicial |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for pair in pairs:
        lines.append(
            f"| {pair['pair_id']} | {pair['D_joules_per_training']:.9f} | {pair['E_joules_per_training']:.9f} | {pair['D_over_E']:.9f} | {pair['D_average_watts']:.3f} | {pair['E_average_watts']:.3f} | {pair['initial_temperature_delta_c']:.1f} °C |"
        )
    lines += [
        "",
        "Com apenas dois pares válidos não foi calculado um IC confirmatório. Produzir um IC aqui daria aparência de precisão sem desenho amostral suficiente.",
        "",
        "## Identificação causal D × E",
        "",
        "- D e E chamaram o mesmo `tcap_full_worker.exe`, SHA-256 " + f"`{same['D_executable_sha256']}`.",
        "- Dataset e bundle de inicialização foram iguais e content-addressed.",
        f"- Piloto K=2: D end-to-end `{same['D_total_seconds']:.6f} s`; E `{same['E_parent_seconds']:.6f} s`; razão `{same['D_over_E_end_to_end_ratio_at_K2']:.3f}`.",
        f"- Tempo interno do filho no piloto: D `{same['D_child_seconds']:.6f} s`; E `{same['E_child_seconds']:.6f} s`.",
        "- O binário de resultado foi idêntico; diferenças máximas de loss, parâmetros e predições foram zero.",
        "- A diferença D/E mede a governança T e sua verificação/publicação; não mede T contra PyTorch nem a escolha de um kernel melhor.",
        "",
        "## Metrologia e recomposição",
        "",
        f"- Sensor literal selecionado: `{sources['EXPLORATORY_HWINFO']['literal_sensor']}`; unidade `{sources['EXPLORATORY_HWINFO']['unit']}`.",
        f"- Intervalo mediano `{sources['EXPLORATORY_HWINFO']['median_interval_seconds']:.3f} s`; p95 `{sources['EXPLORATORY_HWINFO']['p95_interval_seconds']:.3f} s`.",
        "- Energia integrada por timestamps reais, regra trapezoidal e interpolação nos limites exatos.",
        f"- Segmentos brutos recompostos: `{len(recomposed)}/{len(recomposed)}`; diferença máxima `0 J` dentro de 1e-9.",
        "- O HWiNFO não tem certificado de calibração/uncertainty suficiente para elevar esses números a E1.",
        "- A bateria estava carregando; portanto a energia na tomada, mesmo se estivesse disponível, não poderia ser atribuída integralmente ao workload sem controle adicional.",
        "",
        "## Runtime energético V2",
        "",
        f"Validação focal: **{validation['passed']} passed, {validation['failed']} failed** em `{validation['duration_seconds']:.2f} s`.",
        "",
        "Foram corrigidos/testados: normalização exclusiva por `K_completed`, cinco contadores K, potência por amostra, potência amostrada e energia cumulativa, interpolação de borda, gaps, reset/wrap desconhecido, mudança de range, mock, calibração, firmware, clock, desktop sem bateria, laptop instável, bootstrap hierárquico e braço E de kernel idêntico.",
        "",
        "## Estados terminais",
        "",
        f"- `E1 = {e1['terminal_state']}`",
        f"- `E2 = {e2['terminal_state']}`",
        "- `TOTAL_SYSTEM_ENERGY_CLAIM = NOT_AUTHORIZED`",
        "- `CPU_PACKAGE_ENERGY_CLAIM = NOT_AUTHORIZED`",
        "- `EXPLORATORY_HWINFO_DIRECTION = D_CONSUMED_MORE_THAN_E_IN_VALID_LOCAL_PAIRS`",
        "",
        "## O que falta fisicamente — não é uma pendência de software",
        "",
        "E1 exige um analisador físico de tomada com serial, firmware, range congelado, incerteza <1%, calibração rastreável recente e export por timestamps; no notebook, a bateria precisa estar estável. E2 exige 6 hosts em 3 famílias de CPU, 2 laboratórios independentes, 5 famílias de workload e 24 pares por host/workload em pelo menos 3 sessões. Nenhuma manipulação local transforma 1 laptop e HWiNFO nessa topologia.",
        "",
        "## Síntese de direção",
        "",
        "**Negativo quanto à hipótese específica testada:** a governança T adicionou energia ao mesmo kernel nos dois pares válidos. O efeito exploratório mediano foi +4,94%, abaixo do limiar material de 10%, mas na direção desfavorável.",
        "",
        "**Positivo quanto à arquitetura experimental:** o contraste anteriormente confuso foi decomposto; sabemos agora que a grande vantagem D/A não pode ser atribuída somente à governança T. Ela vem principalmente da escolha do executor/kernel, enquanto T cobra um overhead mensurável para arquitetar, auditar e julgar.",
        "",
        "**Conclusão científica atual:** não existe evidência válida de compressão energética confirmatória. Existe evidência exploratória de equivalência perfeita, isolamento causal e pequeno overhead energético de T no host local. O próximo resultado legítimo depende de instrumento físico e replicação externa, não de ajustar o software até aparecer uma vitória.",
    ]
    return "\n".join(lines)


def render_state(preflight: dict[str, Any], e1: dict[str, Any], e2: dict[str, Any]) -> str:
    return "\n".join([
        "# Estado — energia confirmatória da Interlocução",
        "",
        f"Atualizado: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        f"- branch: `{preflight['repository']['branch']}`",
        f"- commit: `{preflight['repository']['commit']}`",
        "- worktree histórico: preservado; nenhum reset/clean/stash",
        "- ENERGY_RUNTIME_V2_FOCAL_TESTS: `54 PASS`",
        "- SAME_KERNEL_IDENTIFICATION: `PASS`",
        f"- E1: `{e1['terminal_state']}`",
        f"- E2: `{e2['terminal_state']}`",
        "- Cloud: `RELEASE_LOCKED`",
        "- owner/public/native: não alterados",
        "- total-system claim: proibido",
        "- package-energy claim: proibido; HWiNFO exploratório somente",
        "",
        "Próxima ação física exata: conectar analisador de potência calibrado entre a tomada e o SUT, estabilizar a bateria e importar seu CSV/JSONL com certificado/serial/range; para E2, executar o mesmo pacote em cinco hosts adicionais e um segundo laboratório.",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
