"""Profiler causal e estrutural da Álgebra Casulo/T.

Este módulo não cronometra e não declara vencedor. Ele transforma o plano
compilado em uma contabilidade auditável de trabalho, tráfego e materialização,
para que otimizações posteriores ataquem causas explícitas.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .autograd import MetamorfoseAutogradIR, compile_autograd_file
from .tensor_cpu import (
    DEFAULT_ARENA_BUDGET_BYTES,
    TensorCpuPlan,
    TensorCpuProviderChoice,
    plan_tensor_cpu,
)


CAUSAL_PROFILE_PROTOCOL = "casulo-causal-profile/0.1"
CAUSAL_ABLATION_PROTOCOL = "casulo-causal-ablation-plan/0.1"


class CausalProfilerError(RuntimeError):
    """O perfil causal não pode ser produzido sem inventar informação."""


@dataclass(frozen=True, slots=True)
class CausalProfile:
    directory: Path
    json_path: Path
    html_path: Path
    document: dict[str, Any]


def create_causal_profile(
    graph_path: str | Path,
    output_directory: str | Path,
    *,
    wrt: Iterable[str],
    loss: str | None = None,
    workers: int | str = "auto",
    gemm_workers: int | str | None = None,
    provider: TensorCpuProviderChoice = "owned",
    arena_budget_bytes: int = DEFAULT_ARENA_BUDGET_BYTES,
) -> CausalProfile:
    graph = Path(graph_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    json_path = output / "causal-profile.json"
    html_path = output / "causal-profile.html"
    if json_path.exists() or html_path.exists():
        raise CausalProfilerError(
            f"perfil causal já existe e é imutável: {output}"
        )
    autograd = compile_autograd_file(
        graph,
        wrt=tuple(wrt),
        loss=loss,
    )
    plan = plan_tensor_cpu(
        autograd,
        arena_budget_bytes=arena_budget_bytes,
        workers=workers,
        gemm_workers=gemm_workers,
        provider=provider,
    )
    if not plan.eligible:
        raise CausalProfilerError(
            f"plano inelegível ao profiler: {plan.reason}"
        )
    body = _profile_document(autograd, plan, graph)
    seal = _body_sha256(body)
    document = {
        **body,
        "profile_id": f"sha256:{seal}",
        "seal": {
            "algorithm": "sha256",
            "canonical_body_sha256": seal,
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_new_json(json_path, document)
    html_path.write_text(
        _render_html(document),
        encoding="utf-8",
        newline="\n",
    )
    return CausalProfile(output, json_path, html_path, document)


def _profile_document(
    autograd: MetamorfoseAutogradIR,
    plan: TensorCpuPlan,
    graph: Path,
) -> dict[str, Any]:
    values = _value_types(autograd)
    allocated_values = {
        value
        for buffer in plan.buffers
        for value in buffer.values
    }
    buffer_by_value = {
        value: {
            "alias_group": buffer.alias_group,
            "offset": buffer.offset,
            "slot_bytes": buffer.slot_bytes,
            "first_instruction": buffer.first_instruction,
            "last_instruction": buffer.last_instruction,
        }
        for buffer in plan.buffers
        for value in buffer.values
    }
    regions = {
        (region.stage, index): region
        for region in plan.fusion_regions
        for index in range(
            region.first_instruction,
            region.last_instruction + 1,
        )
    }
    kernel_iter = iter(plan.algebra_kernels)
    instructions: list[dict[str, Any]] = []
    global_index = 0
    for stage, stage_instructions in (
        ("forward", autograd.forward.instructions),
        ("backward", autograd.backward),
    ):
        for stage_index, instruction in enumerate(stage_instructions):
            output_type = instruction.output_type
            output_elements = int(output_type.numel or 0)
            output_bytes = int(output_type.nbytes or 0)
            input_bytes = sum(
                int(values[name].nbytes or 0)
                for name in instruction.inputs
            )
            materialized = instruction.result in allocated_values
            kernel = (
                next(kernel_iter)
                if instruction.operator == "matmul"
                else None
            )
            flops, flops_known, flop_method = _operation_flops(
                instruction.operator,
                instruction.inputs,
                values,
                output_elements,
                kernel,
            )
            category = _category(instruction.operator, materialized)
            logical_bytes = (
                input_bytes + output_bytes
                if materialized
                else 0
            )
            region = regions.get((stage, stage_index))
            instructions.append(
                {
                    "global_index": global_index,
                    "stage": stage,
                    "stage_index": stage_index,
                    "result": instruction.result,
                    "operator": instruction.operator,
                    "inputs": list(instruction.inputs),
                    "dtype": output_type.dtype.value,
                    "shape": [
                        int(item)
                        for item in output_type.shape
                        if item is not None
                    ],
                    "output_elements": output_elements,
                    "input_logical_bytes": input_bytes,
                    "output_logical_bytes": output_bytes,
                    "logical_traffic_bytes": logical_bytes,
                    "materialized": materialized,
                    "buffer": buffer_by_value.get(instruction.result),
                    "category": category,
                    "scalar_flops": flops,
                    "scalar_flops_known": flops_known,
                    "flop_accounting": flop_method,
                    "arithmetic_intensity_flops_per_byte": (
                        flops / logical_bytes
                        if flops_known and logical_bytes > 0
                        else None
                    ),
                    "fusion_region": (
                        {
                            "first_instruction": (
                                region.first_instruction
                            ),
                            "last_instruction": region.last_instruction,
                            "fused": region.fused,
                            "operators": list(region.operators),
                        }
                        if region is not None
                        else None
                    ),
                    "gemm": (
                        {
                            "identity": kernel.identity,
                            "provider": kernel.provider.to_dict(),
                            "traffic": kernel.traffic.to_dict(),
                            "loop_order": kernel.loop_order,
                            "parallel_axis": kernel.parallel_axis,
                            "vector_axis": kernel.vector_axis,
                            "materializes_left": (
                                kernel.materializes_left
                            ),
                            "materializes_right": (
                                kernel.materializes_right
                            ),
                        }
                        if kernel is not None
                        else None
                    ),
                    "claim": None,
                }
            )
            global_index += 1
    summary = _summarize(instructions, plan)
    return {
        "protocol": CAUSAL_PROFILE_PROTOCOL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "brand": {
            "invention": "Casulo",
            "origin": "Teloscorp",
            "specialty": "Otimização de Tráfego de Informação",
        },
        "graph": {
            "path_hint": graph.name,
            "source_sha256": _file_sha256(graph),
            "autograd_graph_sha256": plan.graph_sha256,
            "loss": autograd.loss,
            "wrt": list(autograd.wrt),
        },
        "plan": plan.to_dict(),
        "instructions": instructions,
        "summary": summary,
        "ablation_plan": _ablation_plan(autograd),
        "scientific": {
            "runtime_measured": False,
            "winner_selected": False,
            "speedup": None,
            "claim": None,
            "limitations": [
                "bytes são tráfego lógico, não contadores de hardware",
                "cache e prefetch não são inferidos",
                "FLOPs transcendentais permanecem desconhecidos",
                "hipóteses de gargalo exigem ablação temporal posterior",
            ],
        },
    }


def _summarize(
    instructions: list[dict[str, Any]],
    plan: TensorCpuPlan,
) -> dict[str, Any]:
    known_flops = sum(
        int(item["scalar_flops"] or 0)
        for item in instructions
        if item["scalar_flops_known"]
    )
    unknown_flop_instructions = sum(
        not item["scalar_flops_known"] for item in instructions
    )
    logical_traffic = sum(
        int(item["logical_traffic_bytes"]) for item in instructions
    )
    gemm_flops = sum(
        int(item["scalar_flops"] or 0)
        for item in instructions
        if item["category"] == "GEMM"
    )
    gemm_traffic = sum(
        int(item["logical_traffic_bytes"])
        for item in instructions
        if item["category"] == "GEMM"
    )
    views = [
        item for item in instructions if item["category"] == "VIEW"
    ]
    fused_regions = [
        region for region in plan.fusion_regions if region.fused
    ]
    logical_allocated = sum(
        int(item["output_logical_bytes"])
        for item in instructions
        if item["materialized"]
    )
    arena = int(plan.arena_required_bytes or 0)
    hypotheses: list[dict[str, Any]] = []
    if known_flops and gemm_flops / known_flops >= 0.8:
        hypotheses.append(
            {
                "priority": 1,
                "code": "GEMM_DOMINATED",
                "evidence": {
                    "known_flop_fraction": gemm_flops / known_flops,
                },
                "falsifier": (
                    "ablação do provedor e das threads GEMM não altera "
                    "materialmente o tempo"
                ),
            }
        )
    if logical_traffic and known_flops / logical_traffic < 5:
        hypotheses.append(
            {
                "priority": 2,
                "code": "LOW_ARITHMETIC_INTENSITY",
                "evidence": {
                    "known_flops_per_logical_byte": (
                        known_flops / logical_traffic
                    ),
                },
                "falsifier": (
                    "reduzir materializações não altera materialmente o tempo"
                ),
            }
        )
    if len(instructions) >= 12:
        hypotheses.append(
            {
                "priority": 3,
                "code": "DISPATCH_OR_LOOP_OVERHEAD",
                "evidence": {
                    "instruction_count": len(instructions),
                    "fused_region_count": len(fused_regions),
                },
                "falsifier": (
                    "fundir regiões ou reduzir lançamentos não altera "
                    "materialmente o tempo"
                ),
            }
        )
    return {
        "instruction_count": len(instructions),
        "category_counts": {
            category: sum(
                item["category"] == category for item in instructions
            )
            for category in ("GEMM", "POINTWISE", "REDUCTION", "VIEW")
        },
        "known_scalar_flops": known_flops,
        "unknown_flop_instruction_count": unknown_flop_instructions,
        "logical_traffic_bytes": logical_traffic,
        "known_arithmetic_intensity_flops_per_byte": (
            known_flops / logical_traffic if logical_traffic else None
        ),
        "gemm_known_flops": gemm_flops,
        "gemm_known_flop_fraction": (
            gemm_flops / known_flops if known_flops else None
        ),
        "gemm_logical_traffic_bytes": gemm_traffic,
        "view_count": len(views),
        "view_output_bytes_not_materialized": sum(
            int(item["output_logical_bytes"]) for item in views
        ),
        "fused_region_count": len(fused_regions),
        "loop_launches_avoided_by_fusion": sum(
            len(region.results) - 1 for region in fused_regions
        ),
        "logical_allocated_output_bytes": logical_allocated,
        "arena_required_bytes": arena,
        "arena_reuse_bytes": max(0, logical_allocated - arena),
        "arena_reuse_ratio": (
            1 - arena / logical_allocated
            if logical_allocated
            else 0.0
        ),
        "hypotheses": hypotheses,
        "claim": None,
    }


def _ablation_plan(
    autograd: MetamorfoseAutogradIR,
) -> dict[str, Any]:
    variants: list[dict[str, Any]] = []
    for provider, workers, gemm_workers in (
        ("owned", 1, 1),
        ("owned", 2, 2),
        ("owned", 4, 4),
        ("openblas", 4, 1),
        ("openblas", 4, 2),
        ("openblas", 4, 4),
    ):
        try:
            plan = plan_tensor_cpu(
                autograd,
                workers=workers,
                gemm_workers=gemm_workers,
                provider=provider,
            )
            variants.append(
                {
                    "id": f"{provider}-w{workers}-g{gemm_workers}",
                    "provider": provider,
                    "workers": workers,
                    "gemm_workers": gemm_workers,
                    "status": (
                        "AVAILABLE" if plan.eligible else "INELIGIBLE"
                    ),
                    "reason": plan.reason,
                    "plan_graph_sha256": plan.graph_sha256,
                    "provider_identity": (
                        plan.algebra_kernels[0].provider.to_dict()
                        if plan.algebra_kernels
                        else None
                    ),
                }
            )
        except Exception as exc:
            variants.append(
                {
                    "id": f"{provider}-w{workers}-g{gemm_workers}",
                    "provider": provider,
                    "workers": workers,
                    "gemm_workers": gemm_workers,
                    "status": "UNAVAILABLE",
                    "reason": " ".join(str(exc).split())[:500],
                    "plan_graph_sha256": None,
                    "provider_identity": None,
                }
            )
    return {
        "protocol": CAUSAL_ABLATION_PROTOCOL,
        "selection_metric": (
            "causal attribution only; no variant may be selected by a "
            "single favorable timing"
        ),
        "variants": variants,
        "required_controls": [
            "same graph and inputs",
            "same CPU affinity",
            "same measurement duration",
            "all failures retained",
            "quality gates before timing",
        ],
        "claim": None,
    }


def _operation_flops(
    operator: str,
    inputs: tuple[str, ...],
    values: Mapping[str, Any],
    output_elements: int,
    kernel: Any,
) -> tuple[int | None, bool, str]:
    if kernel is not None:
        return (
            int(kernel.traffic.scalar_flops),
            True,
            "exact-matmul-2mnk",
        )
    if operator in {"sigmoid", "tanh"}:
        return None, False, "transcendental-cost-unknown"
    if operator in {"zeros_like", "ones_like", "sum_backward"}:
        return 0, True, "write-or-broadcast-without-scalar-flop"
    if operator in {"reshape", "transpose"}:
        return 0, True, "view"
    if operator == "reduce_to_shape":
        source = values[inputs[0]]
        if source.shape == values.get(
            inputs[0], source
        ).shape and source.numel == output_elements:
            return 0, True, "identity-view"
        return int(source.numel or 0), True, "reduction-upper-bound"
    if operator in {"sum", "mean"}:
        source_elements = int(values[inputs[0]].numel or 0)
        return (
            max(0, source_elements - output_elements)
            + (output_elements if operator == "mean" else 0),
            True,
            "reduction-additions-plus-mean-divisions",
        )
    multipliers = {
        "add": 1,
        "sub": 1,
        "mul": 1,
        "div": 1,
        "neg": 1,
        "relu": 1,
        "relu_backward": 2,
        "sigmoid_backward": 4,
        "tanh_backward": 4,
        "mean_backward": 1,
    }
    if operator in multipliers:
        return (
            output_elements * multipliers[operator],
            True,
            "operator-scalar-count",
        )
    return None, False, "operator-cost-not-modeled"


def _category(operator: str, materialized: bool) -> str:
    if operator == "matmul":
        return "GEMM"
    if operator in {
        "sum",
        "mean",
        "reduce_to_shape",
        "sum_backward",
        "mean_backward",
    }:
        return "REDUCTION" if materialized else "VIEW"
    if operator in {"reshape", "transpose"}:
        return "VIEW"
    return "POINTWISE"


def _value_types(
    autograd: MetamorfoseAutogradIR,
) -> dict[str, Any]:
    values = {
        item.name: item.type for item in autograd.forward.inputs
    }
    values.update(
        {
            item.result: item.output_type
            for item in autograd.forward.instructions
        }
    )
    values.update(
        {
            item.result: item.output_type
            for item in autograd.backward
        }
    )
    return values


def _render_html(document: Mapping[str, Any]) -> str:
    summary = document["summary"]
    rows = "".join(
        (
            "<tr>"
            f"<td>{item['global_index']}</td>"
            f"<td>{html.escape(item['stage'])}</td>"
            f"<td>{html.escape(item['operator'])}</td>"
            f"<td>{html.escape(item['category'])}</td>"
            f"<td>{item['logical_traffic_bytes']:,}</td>"
            f"<td>{html.escape(str(item['scalar_flops']))}</td>"
            f"<td>{'sim' if item['materialized'] else 'não'}</td>"
            "</tr>"
        )
        for item in document["instructions"]
    )
    hypotheses = "".join(
        (
            "<li><strong>"
            + html.escape(item["code"])
            + "</strong>: "
            + html.escape(item["falsifier"])
            + "</li>"
        )
        for item in summary["hypotheses"]
    )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Casulo/T — perfil causal</title>
<style>
body{{font-family:Inter,Segoe UI,sans-serif;background:#09111f;color:#eaf1ff;
margin:0;padding:32px}}main{{max-width:1200px;margin:auto}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
article{{background:#121f35;border:1px solid #29405f;border-radius:14px;
padding:16px}}table{{width:100%;border-collapse:collapse;background:#101b2e;
margin-top:24px}}th,td{{padding:10px;border-bottom:1px solid #29405f;
text-align:left}}code{{color:#84e8ca}}.guard{{color:#ffcf7d}}
</style></head><body><main>
<p>Teloscorp · Casulo · Otimização de Tráfego de Informação</p>
<h1>Perfil causal da Álgebra Casulo/T</h1>
<p class="guard">Sem cronômetro, vencedor ou claim. Este artefato descreve
causas estruturais a serem refutadas por ablação.</p>
<div class="cards">
<article><small>Instruções</small><h2>{summary['instruction_count']}</h2></article>
<article><small>FLOPs conhecidos</small><h2>{summary['known_scalar_flops']:,}</h2></article>
<article><small>Tráfego lógico</small><h2>{summary['logical_traffic_bytes']:,} B</h2></article>
<article><small>Reuso de arena</small><h2>{summary['arena_reuse_ratio']:.1%}</h2></article>
</div>
<h2>Hipóteses refutáveis</h2><ol>{hypotheses}</ol>
<table><thead><tr><th>#</th><th>Fase</th><th>Operador</th><th>Classe</th>
<th>Bytes lógicos</th><th>FLOPs</th><th>Materializa</th></tr></thead>
<tbody>{rows}</tbody></table>
<p>Perfil: <code>{html.escape(document['profile_id'])}</code></p>
</main></body></html>"""


def _body_sha256(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_new_json(
    path: Path,
    document: Mapping[str, Any],
) -> None:
    if path.exists():
        raise CausalProfilerError(f"arquivo imutável já existe: {path}")
    path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
