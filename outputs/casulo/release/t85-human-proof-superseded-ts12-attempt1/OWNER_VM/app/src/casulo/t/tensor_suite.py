"""Suíte confirmatória multi-caso e multi-processo do Casulo/T.

Cada caso usa o laboratório tensorial como unidade de medição. Esta camada
sela todos os casos antes da execução, força processos novos e agrega sem
selecionar o melhor resultado.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .tensor_lab import (
    TENSOR_LAB_BACKEND_EAGER,
    TENSOR_LAB_BACKEND_INDUCTOR,
    create_tensor_lab_preregistration,
    verify_tensor_lab_chain,
    verify_tensor_lab_preregistration,
)


TENSOR_SUITE_CASES_PROTOCOL = "casulo-tensor-suite-cases/0.1"
TENSOR_SUITE_PREREGISTRATION_PROTOCOL = (
    "casulo-tensor-suite-preregistration/0.1"
)
TENSOR_SUITE_REPORT_PROTOCOL = "casulo-tensor-suite-report/0.1"
TENSOR_SUITE_VERDICT_PROTOCOL = "casulo-tensor-suite-verdict/0.1"
TENSOR_SUITE_BASELINES = (
    TENSOR_LAB_BACKEND_EAGER,
    TENSOR_LAB_BACKEND_INDUCTOR,
)
_CASE_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,47}$")


class TensorSuiteError(RuntimeError):
    """Contrato, execução ou evidência inválida da suíte."""


@dataclass(frozen=True, slots=True)
class TensorSuitePreregistration:
    directory: Path
    path: Path
    experiment_id: str
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TensorSuiteReport:
    directory: Path
    json_path: Path
    html_path: Path
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TensorSuiteVerdict:
    path: Path
    classification: str
    document: dict[str, Any]


def create_tensor_suite_preregistration(
    cases_manifest_path: str | Path,
    output_directory: str | Path,
    *,
    samples: int = 9,
    warmups: int = 2,
    inner_iterations: int = 25,
    restarts: int = 3,
    workers: int = 4,
    gemm_workers: int = 1,
    provider: str = "openblas",
    seed: int = 20_260_730,
    bootstrap_resamples: int = 2_000,
    superiority_threshold: float = 1.0,
    commercial_threshold: float = 6.0,
    prior_exploratory_disclosure: str | None = None,
    claim_eligible: bool = True,
) -> TensorSuitePreregistration:
    manifest_path = Path(cases_manifest_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise TensorSuiteError(
            f"diretório de pré-registro já existe e é imutável: {output}"
        )
    if restarts < 3:
        raise TensorSuiteError(
            "suíte confirmatória exige ao menos três reinícios"
        )
    cases = _load_cases_manifest(manifest_path)
    output.mkdir(parents=True)
    child_directory = output / "cases"
    child_directory.mkdir()
    child_records: list[dict[str, Any]] = []
    for case in cases:
        child_path = child_directory / f"{case['name']}.json"
        child = create_tensor_lab_preregistration(
            case["graph"],
            child_path,
            wrt=tuple(case["wrt"]),
            loss=case.get("loss"),
            samples=samples,
            warmups=warmups,
            inner_iterations=inner_iterations,
            workers=workers,
            gemm_workers=gemm_workers,
            provider=provider,
            seed=seed ^ _stable_seed(case["name"]),
            bootstrap_resamples=bootstrap_resamples,
            superiority_threshold=superiority_threshold,
            commercial_threshold=commercial_threshold,
            prior_exploratory_disclosure=prior_exploratory_disclosure,
            prior_same_design_observed=False,
            claim_eligible=False,
        )
        design = child.document["design"]
        child_records.append(
            {
                "name": case["name"],
                "graph_path_hint": os.path.relpath(
                    case["graph"],
                    manifest_path.parent,
                ).replace("\\", "/"),
                "graph_sha256": design["graph"]["sha256"],
                "autograd_graph_sha256": design["graph"][
                    "autograd_graph_sha256"
                ],
                "wrt": list(case["wrt"]),
                "loss": design["loss"],
                "child_preregistration": (
                    f"cases/{case['name']}.json"
                ),
                "child_preregistration_sha256": _file_sha256(child.path),
                "child_experiment_id": child.experiment_id,
            }
        )
    schedule = _execution_schedule(
        [item["name"] for item in child_records],
        restarts,
    )
    body: dict[str, Any] = {
        "protocol": TENSOR_SUITE_PREREGISTRATION_PROTOCOL,
        "brand": {
            "invention": "Casulo",
            "origin": "Teloscorp",
            "specialty": "Otimização de Tráfego de Informação",
        },
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "observed_suite_results_at_registration": False,
        "trusted_external_timestamp": False,
        "cases_manifest": {
            "path_hint": manifest_path.name,
            "sha256": _normalized_text_sha256(manifest_path),
            "protocol": TENSOR_SUITE_CASES_PROTOCOL,
        },
        "hypothesis": {
            "phase": "MULTI_CASE_CONFIRMATORY",
            "claim_eligible": bool(claim_eligible),
            "prior_exploratory_disclosure": (
                prior_exploratory_disclosure
            ),
            "superiority_threshold": float(superiority_threshold),
            "commercial_threshold": float(commercial_threshold),
            "aggregation": (
                "every-case-every-restart-must-pass-every-baseline"
            ),
            "case_or_restart_selection_forbidden": True,
        },
        "design": {
            "cases": child_records,
            "restarts": int(restarts),
            "samples_per_restart": int(samples),
            "warmups": int(warmups),
            "inner_iterations": int(inner_iterations),
            "workers": int(workers),
            "gemm_workers": int(gemm_workers),
            "provider": child_records
            and verify_tensor_lab_preregistration(
                output / child_records[0]["child_preregistration"]
            ).document["design"]["gemm_provider"],
            "required_baselines": list(TENSOR_SUITE_BASELINES),
            "schedule": schedule,
            "process_policy": "fresh-python-process-per-case-restart",
            "cache_policy": "isolated-native-and-inductor-cache-per-run",
            "failure_policy": "failed-and-missing-runs-remain-evidence",
            "seed": int(seed),
            "implementation": _implementation_identity(),
        },
        "result_policy": {
            "overwrite": False,
            "all_scheduled_runs_required": True,
            "positive_requires_unanimity": True,
            "energy_unmeasured_is_null": True,
        },
    }
    seal = _body_seal(body)
    document = {
        **body,
        "experiment_id": f"sha256:{seal}",
        "seal": {
            "algorithm": "sha256",
            "canonical_body_sha256": seal,
        },
    }
    path = output / "suite-preregistration.json"
    _write_new_json(path, document)
    return TensorSuitePreregistration(
        directory=output,
        path=path,
        experiment_id=document["experiment_id"],
        document=document,
    )


def verify_tensor_suite_preregistration(
    path: str | Path,
) -> TensorSuitePreregistration:
    source = Path(path).expanduser().resolve()
    document = json.loads(source.read_text(encoding="utf-8"))
    _verify_seal(
        document,
        TENSOR_SUITE_PREREGISTRATION_PROTOCOL,
        "experiment_id",
    )
    if document.get("observed_suite_results_at_registration") is not False:
        raise TensorSuiteError(
            "pré-registro contaminado por resultado da suíte"
        )
    for case in document["design"]["cases"]:
        child_path = source.parent / case["child_preregistration"]
        if _file_sha256(child_path) != case[
            "child_preregistration_sha256"
        ]:
            raise TensorSuiteError(
                f"pré-registro filho adulterado: {case['name']}"
            )
        child = verify_tensor_lab_preregistration(child_path)
        if child.experiment_id != case["child_experiment_id"]:
            raise TensorSuiteError(
                f"identidade do caso diverge: {case['name']}"
            )
        if child.document["hypothesis"]["claim_eligible"] is not False:
            raise TensorSuiteError(
                "somente o Juiz da suíte pode liberar claim agregado"
            )
    return TensorSuitePreregistration(
        directory=source.parent,
        path=source,
        experiment_id=document["experiment_id"],
        document=document,
    )


def run_tensor_suite(
    cases_manifest_path: str | Path,
    preregistration_path: str | Path,
    output_directory: str | Path,
) -> TensorSuiteReport:
    manifest_path = Path(cases_manifest_path).expanduser().resolve()
    prereg = verify_tensor_suite_preregistration(preregistration_path)
    output = Path(output_directory).expanduser().resolve()
    report_path = output / "suite-report.json"
    html_path = output / "suite-report.html"
    if output.exists():
        raise TensorSuiteError(
            f"resultado da suíte já existe e é imutável: {output}"
        )
    resolved_cases = {
        item["name"]: item
        for item in _load_cases_manifest(manifest_path)
    }
    _bind_manifest(prereg.document, manifest_path, resolved_cases)
    output.mkdir(parents=True)
    runs: list[dict[str, Any]] = []
    for scheduled in prereg.document["design"]["schedule"]:
        case_name = scheduled["case"]
        restart = int(scheduled["restart"])
        ordinal = int(scheduled["ordinal"])
        run_directory = (
            output
            / "runs"
            / f"{ordinal:03d}-{case_name}-r{restart}"
        )
        child_record = next(
            item
            for item in prereg.document["design"]["cases"]
            if item["name"] == case_name
        )
        child_prereg = (
            prereg.directory
            / child_record["child_preregistration"]
        )
        graph = Path(resolved_cases[case_name]["graph"])
        run_command = [
            sys.executable,
            "-m",
            "casulo.t.cli",
            "tensor-lab-run",
            str(graph),
            "--preregistration",
            str(child_prereg),
            "--output",
            str(run_directory),
        ]
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONHASHSEED": str(
                    prereg.document["design"]["seed"]
                ),
                "OMP_DYNAMIC": "FALSE",
                "KMP_DYNAMIC": "FALSE",
            }
        )
        run_process = subprocess.run(
            run_command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        entry: dict[str, Any] = {
            **scheduled,
            "status": "FAILED",
            "run_returncode": run_process.returncode,
            "run_stdout_tail": run_process.stdout[-2_000:],
            "run_stderr_tail": run_process.stderr[-2_000:],
            "judge_returncode": None,
            "report": None,
            "report_sha256": None,
            "verdict": None,
            "verdict_sha256": None,
        }
        child_report = run_directory / "tensor-lab-report.json"
        child_verdict = run_directory / "tensor-lab-verdict.json"
        if run_process.returncode == 0 and child_report.is_file():
            judge_process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "casulo.t.cli",
                    "tensor-lab-judge",
                    "--preregistration",
                    str(child_prereg),
                    "--report",
                    str(child_report),
                    "--output",
                    str(child_verdict),
                ],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
            )
            entry["judge_returncode"] = judge_process.returncode
            entry["judge_stdout_tail"] = judge_process.stdout[-2_000:]
            entry["judge_stderr_tail"] = judge_process.stderr[-2_000:]
            if (
                judge_process.returncode == 0
                and child_verdict.is_file()
            ):
                verify_tensor_lab_chain(
                    child_prereg,
                    child_report,
                    child_verdict,
                )
                entry.update(
                    {
                        "status": "COMPLETE",
                        "report": str(
                            child_report.relative_to(output)
                        ).replace("\\", "/"),
                        "report_sha256": _file_sha256(child_report),
                        "verdict": str(
                            child_verdict.relative_to(output)
                        ).replace("\\", "/"),
                        "verdict_sha256": _file_sha256(child_verdict),
                    }
                )
        runs.append(entry)
    complete = all(item["status"] == "COMPLETE" for item in runs)
    body = {
        "protocol": TENSOR_SUITE_REPORT_PROTOCOL,
        "experiment_id": prereg.experiment_id,
        "preregistration_file_sha256": _file_sha256(prereg.path),
        "started_with_all_cases_sealed": True,
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "schedule": prereg.document["design"]["schedule"],
        "runs": runs,
        "environment": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "fresh_process_per_run": True,
        },
        "claims_allowed": False,
        "claim": None,
    }
    _write_new_json(report_path, body)
    html_path.write_text(
        _render_suite_html(body),
        encoding="utf-8",
        newline="\n",
    )
    return TensorSuiteReport(
        directory=output,
        json_path=report_path,
        html_path=html_path,
        document=body,
    )


def judge_tensor_suite(
    preregistration_path: str | Path,
    report_path: str | Path,
    output_path: str | Path,
) -> TensorSuiteVerdict:
    prereg = verify_tensor_suite_preregistration(preregistration_path)
    report_file = Path(report_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise TensorSuiteError(f"veredito já existe: {output}")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    integrity_failures: list[str] = []
    if report.get("protocol") != TENSOR_SUITE_REPORT_PROTOCOL:
        integrity_failures.append("UNKNOWN_SUITE_REPORT_PROTOCOL")
    if report.get("experiment_id") != prereg.experiment_id:
        integrity_failures.append("REPORT_NOT_BOUND_TO_SUITE")
    if report.get("preregistration_file_sha256") != _file_sha256(
        prereg.path
    ):
        integrity_failures.append("PREREGISTRATION_HASH_DIVERGES")
    expected_schedule = prereg.document["design"]["schedule"]
    if report.get("schedule") != expected_schedule:
        integrity_failures.append("SCHEDULE_DIVERGES")
    observed_runs = report.get("runs", [])
    observed_keys = [
        (
            item.get("ordinal"),
            item.get("case"),
            item.get("restart"),
        )
        for item in observed_runs
    ]
    expected_keys = [
        (item["ordinal"], item["case"], item["restart"])
        for item in expected_schedule
    ]
    if observed_keys != expected_keys:
        integrity_failures.append("RUN_SET_OR_ORDER_DIVERGES")
    case_records = {
        item["name"]: item
        for item in prereg.document["design"]["cases"]
    }
    missing_runs: list[str] = []
    run_results: list[dict[str, Any]] = []
    for item in observed_runs:
        label = f"{item.get('case')}#r{item.get('restart')}"
        if item.get("status") != "COMPLETE":
            missing_runs.append(label)
            continue
        report_child = report_file.parent / str(item["report"])
        verdict_child = report_file.parent / str(item["verdict"])
        if (
            _file_sha256(report_child) != item.get("report_sha256")
            or _file_sha256(verdict_child) != item.get("verdict_sha256")
        ):
            integrity_failures.append(f"CHILD_HASH_DIVERGES:{label}")
            continue
        record = case_records[str(item["case"])]
        child_prereg = (
            prereg.directory / record["child_preregistration"]
        )
        try:
            verify_tensor_lab_chain(
                child_prereg,
                report_child,
                verdict_child,
            )
        except Exception as exc:
            integrity_failures.append(
                f"CHILD_CHAIN_INVALID:{label}:{type(exc).__name__}"
            )
            continue
        child_verdict = json.loads(
            verdict_child.read_text(encoding="utf-8")
        )
        if child_verdict.get("claim") is not None:
            integrity_failures.append(f"CHILD_RELEASED_CLAIM:{label}")
        run_results.append(
            {
                "case": item["case"],
                "restart": item["restart"],
                "classification": child_verdict["classification"],
                "baseline_classifications": child_verdict[
                    "baseline_classifications"
                ],
                "metrics": child_verdict["recomputed_metrics"],
                "verdict_sha256": item["verdict_sha256"],
            }
        )
    classification = _classify_suite(
        run_results,
        missing_runs,
        integrity_failures,
        len(expected_schedule),
    )
    hypothesis = prereg.document["hypothesis"]
    claim_eligible = bool(hypothesis["claim_eligible"])
    commercial_threshold = float(hypothesis["commercial_threshold"])
    all_lower_bounds = [
        metric["independent_bootstrap_ci95"]["lower"]
        for item in run_results
        for metric in item["metrics"].values()
        if metric is not None
    ]
    commercial_gate = bool(
        classification == "POSITIVE"
        and claim_eligible
        and len(all_lower_bounds)
        == len(expected_schedule)
        * len(prereg.document["design"]["required_baselines"])
        and all(
            value >= commercial_threshold
            for value in all_lower_bounds
        )
    )
    scope = {
        "cases": [
            {
                "name": item["name"],
                "graph_sha256": item["graph_sha256"],
                "autograd_graph_sha256": item[
                    "autograd_graph_sha256"
                ],
            }
            for item in prereg.document["design"]["cases"]
        ],
        "restarts": prereg.document["design"]["restarts"],
        "workers": prereg.document["design"]["workers"],
        "gemm_workers": prereg.document["design"]["gemm_workers"],
        "provider": prereg.document["design"]["provider"],
        "required_baselines": prereg.document["design"][
            "required_baselines"
        ],
    }
    body = {
        "protocol": TENSOR_SUITE_VERDICT_PROTOCOL,
        "experiment_id": prereg.experiment_id,
        "classification": classification,
        "claim_eligible": claim_eligible,
        "commercial_threshold": commercial_threshold,
        "commercial_gate": commercial_gate,
        "evidence": {
            "preregistration_file_sha256": _file_sha256(prereg.path),
            "report_file_sha256": _file_sha256(report_file),
        },
        "integrity_failures": sorted(set(integrity_failures)),
        "missing_runs": missing_runs,
        "run_results": run_results,
        "scope": scope,
        "claim": (
            {
                "allowed": True,
                "statement": (
                    "Todos os casos, reinícios e baselines selados "
                    "aprovaram superioridade no escopo declarado."
                ),
                "scope": scope,
                "not_proven": [
                    "superioridade geral sobre PyTorch",
                    "mesmo ganho em outros grafos, máquinas ou GPU",
                    "economia de energia elétrica",
                ],
            }
            if classification == "POSITIVE" and claim_eligible
            else None
        ),
        "energy": {"measured": False, "joules": None},
    }
    seal = _body_seal(body)
    document = {
        **body,
        "verdict_id": f"sha256:{seal}",
        "seal": {
            "algorithm": "sha256",
            "canonical_body_sha256": seal,
        },
    }
    _write_new_json(output, document)
    return TensorSuiteVerdict(
        path=output,
        classification=classification,
        document=document,
    )


def verify_tensor_suite_chain(
    preregistration_path: str | Path,
    report_path: str | Path,
    verdict_path: str | Path,
) -> list[str]:
    prereg = verify_tensor_suite_preregistration(preregistration_path)
    report_file = Path(report_path).expanduser().resolve()
    verdict_file = Path(verdict_path).expanduser().resolve()
    report = json.loads(report_file.read_text(encoding="utf-8"))
    verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
    _verify_seal(
        verdict,
        TENSOR_SUITE_VERDICT_PROTOCOL,
        "verdict_id",
    )
    if (
        report.get("experiment_id") != prereg.experiment_id
        or verdict.get("experiment_id") != prereg.experiment_id
    ):
        raise TensorSuiteError("cadeia pertence a experimentos diferentes")
    if verdict["evidence"]["preregistration_file_sha256"] != _file_sha256(
        prereg.path
    ):
        raise TensorSuiteError("hash do pré-registro diverge")
    if verdict["evidence"]["report_file_sha256"] != _file_sha256(
        report_file
    ):
        raise TensorSuiteError("hash do relatório diverge")
    if (
        not verdict["claim_eligible"]
        and (
            verdict["claim"] is not None
            or verdict["commercial_gate"] is not False
        )
    ):
        raise TensorSuiteError("suíte inelegível liberou claim")
    if verdict["energy"] != {"measured": False, "joules": None}:
        raise TensorSuiteError("energia não medida foi preenchida")
    recomputed = _classify_suite(
        verdict["run_results"],
        verdict["missing_runs"],
        verdict["integrity_failures"],
        len(prereg.document["design"]["schedule"]),
    )
    if verdict["classification"] != recomputed:
        raise TensorSuiteError(
            "classificação agregada diverge das evidências"
        )
    return [
        "pré-registro, relatório e veredito pertencem à mesma suíte",
        "casos filhos foram selados antes da execução",
        "ordem e conjunto de reinícios permanecem auditáveis",
        "claim respeita a elegibilidade pré-registrada",
        "energia não medida permanece null",
    ]


def _load_cases_manifest(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != TENSOR_SUITE_CASES_PROTOCOL:
        raise TensorSuiteError("formato de casos desconhecido")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) < 3:
        raise TensorSuiteError("suíte exige ao menos três casos")
    cases: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in raw_cases:
        name = str(raw.get("name", ""))
        if not _CASE_NAME.fullmatch(name) or name in names:
            raise TensorSuiteError(f"nome de caso inválido ou repetido: {name}")
        graph = (path.parent / str(raw["graph"])).resolve()
        if not graph.is_file():
            raise TensorSuiteError(f"grafo ausente: {graph}")
        wrt = tuple(dict.fromkeys(raw.get("wrt", ())))
        if not wrt:
            raise TensorSuiteError(f"caso sem wrt: {name}")
        names.add(name)
        cases.append(
            {
                "name": name,
                "graph": str(graph),
                "wrt": list(wrt),
                "loss": raw.get("loss"),
            }
        )
    return cases


def _execution_schedule(
    names: Sequence[str],
    restarts: int,
) -> list[dict[str, Any]]:
    schedule: list[dict[str, Any]] = []
    ordinal = 0
    for restart in range(restarts):
        rotation = restart % len(names)
        ordered = list(names[rotation:]) + list(names[:rotation])
        for case in ordered:
            schedule.append(
                {
                    "ordinal": ordinal,
                    "case": case,
                    "restart": restart,
                }
            )
            ordinal += 1
    return schedule


def _classify_suite(
    run_results: Sequence[Mapping[str, Any]],
    missing_runs: Sequence[str],
    integrity_failures: Sequence[str],
    expected_runs: int,
) -> str:
    classes = [str(item["classification"]) for item in run_results]
    if integrity_failures:
        return "INVALID"
    if missing_runs or len(run_results) != expected_runs:
        return "INCONCLUSIVE"
    if any(value == "INVALID" for value in classes):
        return "INVALID"
    if any(value == "NEGATIVE" for value in classes):
        return "NEGATIVE"
    if classes and all(value == "POSITIVE" for value in classes):
        return "POSITIVE"
    return "NULL"


def _bind_manifest(
    preregistration: Mapping[str, Any],
    manifest_path: Path,
    cases: Mapping[str, Mapping[str, Any]],
) -> None:
    expected = preregistration["cases_manifest"]
    if _normalized_text_sha256(manifest_path) != expected["sha256"]:
        raise TensorSuiteError("manifesto de casos diverge do pré-registro")
    for record in preregistration["design"]["cases"]:
        case = cases.get(record["name"])
        if case is None:
            raise TensorSuiteError(f"caso ausente: {record['name']}")
        if _normalized_text_sha256(Path(case["graph"])) != record[
            "graph_sha256"
        ]:
            raise TensorSuiteError(f"grafo diverge: {record['name']}")


def _implementation_identity() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {
        name: _file_sha256(root / name)
        for name in (
            "tensor_suite.py",
            "tensor_lab.py",
            "tensor_cpu.py",
            "linear_algebra.py",
            "autograd.py",
        )
    }


def _render_suite_html(document: Mapping[str, Any]) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{item['ordinal']}</td>"
        f"<td>{html.escape(str(item['case']))}</td>"
        f"<td>{item['restart']}</td>"
        f"<td>{html.escape(str(item['status']))}</td>"
        "</tr>"
        for item in document["runs"]
    )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Casulo/T — suíte confirmatória</title>
<style>
body{{font-family:system-ui;margin:2rem;max-width:980px}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:.5rem;border:1px solid #bbb}}
code{{word-break:break-all}}
</style></head><body>
<h1>Casulo/T — suíte confirmatória</h1>
<p>Experimento: <code>{html.escape(str(document['experiment_id']))}</code></p>
<p>Estado: <strong>{html.escape(str(document['status']))}</strong></p>
<table><thead><tr><th>ordem</th><th>caso</th><th>reinício</th><th>estado</th>
</tr></thead><tbody>{rows}</tbody></table>
<p>Nenhum claim é liberado pelo runner. Somente o Juiz agregado decide.</p>
</body></html>
"""


def _stable_seed(text: str) -> int:
    return int.from_bytes(
        hashlib.sha256(text.encode("utf-8")).digest()[:4],
        "big",
    )


def _normalized_text_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _body_seal(body: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_seal(
    document: Mapping[str, Any],
    protocol: str,
    identifier: str,
) -> None:
    if document.get("protocol") != protocol:
        raise TensorSuiteError("protocolo desconhecido")
    seal = document.get("seal", {})
    body = {
        key: value
        for key, value in document.items()
        if key not in {identifier, "seal"}
    }
    actual = _body_seal(body)
    if (
        seal.get("algorithm") != "sha256"
        or seal.get("canonical_body_sha256") != actual
        or document.get(identifier) != f"sha256:{actual}"
    ):
        raise TensorSuiteError("documento adulterado")


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists():
        raise TensorSuiteError(f"arquivo imutável já existe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
