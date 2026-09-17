"""Backend CPU tensorial conservador para a TensorIR e AutogradIR.

O módulo separa planejamento, geração, compilação e execução. Qualquer forma
fora do subconjunto explicitamente suportado retorna fallback; nenhuma falha
de capacidade é promovida a sucesso nativo.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .autograd import (
    AutogradInstruction,
    MetamorfoseAutogradIR,
    _prepare_numeric_inputs,
    compile_autograd_file,
)
from .linear_algebra import (
    CASULO_OWNED_GEMM_PROVIDER,
    CasuloLinearAlgebraError,
    CrisalidaGemmPlan,
    GemmProviderDescriptor,
    discover_numpy_openblas_provider,
    form_gemm_plan,
    resolve_provider_library,
)
from .native import NativeError, _compiler_version, _find_compiler
from .parity import (
    NumpyTensorExecutor,
    ParityStatus,
    PyTorchParityReport,
    TensorExecution,
    compare_executions,
    run_pytorch_parity,
)
from .tensor import (
    CrisalidaTensorIR,
    LarvaTensor,
    TensorDType,
    TensorIRInstruction,
    TensorLayout,
    TensorOwnership,
)


TENSOR_CPU_PLAN_PROTOCOL = "casulo-tensor-cpu-plan/0.4"
TENSOR_CPU_ABI_PROTOCOL = "casulo-tensor-cpu-abi/0.4"
TENSOR_CPU_BUILD_PROTOCOL = "casulo-tensor-cpu-build/0.4"
TENSOR_CPU_RUN_PROTOCOL = "casulo-tensor-cpu-run/0.4"
TENSOR_CPU_PARITY_PROTOCOL = "casulo-tensor-cpu-parity/0.4"
TENSOR_CPU_BACKEND = "casulo-linear-algebra-c99-openmp/0.4"
TENSOR_CPU_ALIGNMENT = 64
DEFAULT_ARENA_BUDGET_BYTES = 64 * 1024 * 1024
TensorCpuProviderChoice = str | GemmProviderDescriptor

_POINTWISE_OPERATORS = {
    "add",
    "sub",
    "mul",
    "div",
    "neg",
    "relu",
    "sigmoid",
    "tanh",
    "relu_backward",
    "sigmoid_backward",
    "tanh_backward",
    "ones_like",
    "zeros_like",
}
_FORWARD_OPERATORS = {
    "add",
    "sub",
    "mul",
    "div",
    "matmul",
    "relu",
    "sigmoid",
    "tanh",
    "sum",
    "mean",
    "reshape",
    "transpose",
}
_BACKWARD_OPERATORS = {
    "ones_like",
    "zeros_like",
    "add",
    "mul",
    "div",
    "neg",
    "matmul",
    "transpose",
    "reshape",
    "reduce_to_shape",
    "relu_backward",
    "sigmoid_backward",
    "tanh_backward",
    "sum_backward",
    "mean_backward",
}
_C_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")


class TensorCpuError(RuntimeError):
    """Falha verificável do backend CPU tensorial."""


class TensorCpuUnavailable(TensorCpuError):
    """Capacidade nativa ausente; o executor pode usar fallback."""


class TensorCpuCompilationError(TensorCpuError):
    """O código C foi gerado, mas não produziu uma biblioteca válida."""


@dataclass(frozen=True, slots=True)
class TensorCpuFusionRegion:
    stage: str
    first_instruction: int
    last_instruction: int
    operators: tuple[str, ...]
    results: tuple[str, ...]
    dtype: str
    shape: tuple[int, ...]
    vectorizable: bool

    @property
    def fused(self) -> bool:
        return len(self.results) > 1

    def to_dict(self) -> dict[str, Any]:
        document = asdict(self)
        document["shape"] = list(self.shape)
        document["fused"] = self.fused
        return document


@dataclass(frozen=True, slots=True)
class TensorCpuBuffer:
    alias_group: str
    offset: int
    nbytes: int
    slot_bytes: int
    first_instruction: int
    last_instruction: int
    values: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TensorCpuPlan:
    protocol: str
    status: str
    reason: str | None
    graph_sha256: str
    arena_budget_bytes: int
    arena_required_bytes: int | None
    alignment_bytes: int
    workers: int
    gemm_workers: int
    gemm_worker_policy: str
    gemm_worker_schedule: tuple[int, ...]
    scheduler: Mapping[str, Any]
    algebra_kernels: tuple[CrisalidaGemmPlan, ...]
    fusion_regions: tuple[TensorCpuFusionRegion, ...]
    buffers: tuple[TensorCpuBuffer, ...]
    supported_forward_operators: tuple[str, ...]
    supported_backward_operators: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return self.status == "NATIVE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "status": self.status,
            "eligible": self.eligible,
            "reason": self.reason,
            "graph_sha256": self.graph_sha256,
            "arena_budget_bytes": self.arena_budget_bytes,
            "arena_required_bytes": self.arena_required_bytes,
            "alignment_bytes": self.alignment_bytes,
            "workers": self.workers,
            "gemm_workers": self.gemm_workers,
            "gemm_worker_policy": self.gemm_worker_policy,
            "gemm_worker_schedule": list(self.gemm_worker_schedule),
            "scheduler": dict(self.scheduler),
            "algebra_kernels": [
                item.to_dict() for item in self.algebra_kernels
            ],
            "fusion_regions": [
                item.to_dict() for item in self.fusion_regions
            ],
            "buffers": [item.to_dict() for item in self.buffers],
            "supported_forward_operators": list(
                self.supported_forward_operators
            ),
            "supported_backward_operators": list(
                self.supported_backward_operators
            ),
        }


@dataclass(frozen=True, slots=True)
class TensorCpuArtifact:
    protocol: str
    backend: str
    graph_sha256: str
    source: str
    source_sha256: str
    plan: TensorCpuPlan

    def to_dict(self, *, include_source: bool = False) -> dict[str, Any]:
        document = {
            "protocol": self.protocol,
            "backend": self.backend,
            "graph_sha256": self.graph_sha256,
            "source_sha256": self.source_sha256,
            "plan": self.plan.to_dict(),
        }
        if include_source:
            document["source"] = self.source
        return document


@dataclass(frozen=True, slots=True)
class TensorCpuBuild:
    protocol: str
    backend: str
    library: Path
    binary_sha256: str
    source_sha256: str
    compiler: str
    compiler_version: str
    command: tuple[str, ...]
    cache_hit: bool
    compilation_wall_ns: int | None
    vectorization_report: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "backend": self.backend,
            "library": str(self.library),
            "binary_sha256": self.binary_sha256,
            "source_sha256": self.source_sha256,
            "compiler": self.compiler,
            "compiler_version": self.compiler_version,
            "command": list(self.command),
            "cache_hit": self.cache_hit,
            "compilation_wall_ns": self.compilation_wall_ns,
            "vectorization_report": list(self.vectorization_report),
        }


@dataclass(frozen=True, slots=True)
class TensorCpuParityReport:
    protocol: str
    status: ParityStatus
    reason: str | None
    reference_backend: str
    reference_version: str
    candidate_backend: str
    candidate_version: str
    graph_sha256: str
    input_sha256: str
    checks: tuple[Any, ...]
    tolerances: tuple[Any, ...]

    @property
    def passed(self) -> bool:
        return self.status is ParityStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "status": self.status.value,
            "passed": self.passed,
            "reason": self.reason,
            "reference_backend": self.reference_backend,
            "reference_version": self.reference_version,
            "candidate_backend": self.candidate_backend,
            "candidate_version": self.candidate_version,
            "graph_sha256": self.graph_sha256,
            "input_sha256": self.input_sha256,
            "checks": [item.to_dict() for item in self.checks],
            "tolerances": [item.to_dict() for item in self.tolerances],
            "timing": None,
            "energy_joules": None,
        }


@dataclass(frozen=True, slots=True)
class TensorCpuRun:
    protocol: str
    status: str
    used_native: bool
    fallback_reason: str | None
    plan: TensorCpuPlan
    build: TensorCpuBuild | None
    execution: TensorExecution
    native_vs_numpy: TensorCpuParityReport | None
    numpy_vs_pytorch: PyTorchParityReport | None
    preparation_wall_ns: int
    execution_wall_ns: int

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "status": self.status,
            "passed": self.passed,
            "used_native": self.used_native,
            "fallback_reason": self.fallback_reason,
            "plan": self.plan.to_dict(),
            "build": self.build.to_dict() if self.build else None,
            "execution": self.execution.to_dict(),
            "validation": {
                "native_vs_numpy": (
                    self.native_vs_numpy.to_dict()
                    if self.native_vs_numpy
                    else None
                ),
                "numpy_vs_pytorch": (
                    self.numpy_vs_pytorch.to_dict()
                    if self.numpy_vs_pytorch
                    else None
                ),
            },
            "timing": {
                "classification": "EXPLORATORY_DIAGNOSTIC",
                "claim_eligible": False,
                "compilation_wall_ns": (
                    self.build.compilation_wall_ns
                    if self.build
                    else None
                ),
                "preparation_wall_ns": self.preparation_wall_ns,
                "execution_wall_ns": self.execution_wall_ns,
            },
            "energy_joules": None,
            "claim": None,
        }


@dataclass(slots=True)
class PreparedTensorCpuExecutor:
    """Executor nativo preparado, sem validação ou alocação no laço medido."""

    autograd: MetamorfoseAutogradIR
    plan: TensorCpuPlan
    build: TensorCpuBuild
    input_arrays: Any
    observed: list[Any]
    input_pointers: Any
    observed_pointers: Any
    arena: dict[str, Any]
    library: Any
    function: Any

    def invoke(self, *, audit: bool = True) -> None:
        status_code = self.function(
            self.input_pointers,
            self.observed_pointers,
            self.arena["pointer"],
            self.plan.arena_required_bytes or 0,
            self.plan.workers,
            int(audit),
        )
        if status_code != 0:
            message = {
                1: "arena insuficiente",
                2: "ponteiro nulo",
                4: "provedor GEMM externo não vinculado",
                3: "workers inválido",
            }.get(status_code, f"status nativo desconhecido {status_code}")
            raise TensorCpuError(message)

    def snapshot(self, reference: TensorExecution) -> TensorExecution:
        return _native_execution(
            self.autograd,
            self.observed,
            reference,
            self.build,
        )


@dataclass(frozen=True, slots=True)
class _InstructionRef:
    stage: str
    stage_index: int
    global_index: int
    instruction: TensorIRInstruction | AutogradInstruction


@dataclass(frozen=True, slots=True)
class _ValueLayout:
    name: str
    tensor: LarvaTensor
    shape: tuple[int, ...]
    strides: tuple[int, ...]
    alias_group: str
    allocated: bool

    @property
    def contiguous(self) -> bool:
        return self.strides == _contiguous_strides(self.shape)


def plan_tensor_cpu(
    autograd: MetamorfoseAutogradIR,
    *,
    arena_budget_bytes: int = DEFAULT_ARENA_BUDGET_BYTES,
    workers: int | str = "auto",
    gemm_workers: int | str | None = None,
    provider: TensorCpuProviderChoice = "owned",
) -> TensorCpuPlan:
    """Cria um plano determinístico ou explica por que o fallback é obrigatório."""

    graph_sha256 = _graph_sha256(autograd)
    selected_provider = _resolve_provider_choice(provider)
    selected_workers, scheduler = _select_workers(autograd, workers)
    selected_gemm_workers, gemm_worker_policy = _select_gemm_workers(
        selected_workers,
        gemm_workers,
        selected_provider,
    )
    reason = _ineligibility_reason(autograd, arena_budget_bytes)
    if reason is not None:
        return TensorCpuPlan(
            protocol=TENSOR_CPU_PLAN_PROTOCOL,
            status="FALLBACK",
            reason=reason,
            graph_sha256=graph_sha256,
            arena_budget_bytes=arena_budget_bytes,
            arena_required_bytes=None,
            alignment_bytes=TENSOR_CPU_ALIGNMENT,
            workers=selected_workers,
            gemm_workers=selected_gemm_workers,
            gemm_worker_policy=gemm_worker_policy,
            gemm_worker_schedule=(),
            scheduler=scheduler,
            algebra_kernels=(),
            fusion_regions=(),
            buffers=(),
            supported_forward_operators=tuple(sorted(_FORWARD_OPERATORS)),
            supported_backward_operators=tuple(sorted(_BACKWARD_OPERATORS)),
        )

    layouts = _value_layouts(autograd)
    instructions = _instruction_refs(autograd)
    buffers, required = _plan_arena(layouts, instructions)
    if required > arena_budget_bytes:
        return TensorCpuPlan(
            protocol=TENSOR_CPU_PLAN_PROTOCOL,
            status="FALLBACK",
            reason=(
                "arena_required_exceeds_budget: "
                f"{required} > {arena_budget_bytes}"
            ),
            graph_sha256=graph_sha256,
            arena_budget_bytes=arena_budget_bytes,
            arena_required_bytes=required,
            alignment_bytes=TENSOR_CPU_ALIGNMENT,
            workers=selected_workers,
            gemm_workers=selected_gemm_workers,
            gemm_worker_policy=gemm_worker_policy,
            gemm_worker_schedule=(),
            scheduler=scheduler,
            algebra_kernels=(),
            fusion_regions=(),
            buffers=buffers,
            supported_forward_operators=tuple(sorted(_FORWARD_OPERATORS)),
            supported_backward_operators=tuple(sorted(_BACKWARD_OPERATORS)),
        )
    regions = _fusion_regions(autograd, layouts)
    algebra_kernels = _form_algebra_kernels(
        autograd,
        layouts,
        selected_provider,
    )
    gemm_worker_schedule = _schedule_gemm_workers(
        algebra_kernels,
        maximum_workers=selected_gemm_workers,
        policy=gemm_worker_policy,
    )
    return TensorCpuPlan(
        protocol=TENSOR_CPU_PLAN_PROTOCOL,
        status="NATIVE",
        reason=None,
        graph_sha256=graph_sha256,
        arena_budget_bytes=arena_budget_bytes,
        arena_required_bytes=required,
        alignment_bytes=TENSOR_CPU_ALIGNMENT,
        workers=selected_workers,
        gemm_workers=selected_gemm_workers,
        gemm_worker_policy=gemm_worker_policy,
        gemm_worker_schedule=gemm_worker_schedule,
        scheduler=scheduler,
        algebra_kernels=algebra_kernels,
        fusion_regions=regions,
        buffers=buffers,
        supported_forward_operators=tuple(sorted(_FORWARD_OPERATORS)),
        supported_backward_operators=tuple(sorted(_BACKWARD_OPERATORS)),
    )


def _ineligibility_reason(
    autograd: MetamorfoseAutogradIR,
    arena_budget_bytes: int,
) -> str | None:
    if arena_budget_bytes <= 0:
        return "arena_budget_must_be_positive"
    values = _all_value_types(autograd)
    if any(item.numel is None for item in values.values()):
        return "dynamic_shape_requires_reference_executor"
    if any(item.rank > 4 for item in values.values()):
        return "rank_above_four_requires_reference_executor"
    if any(
        item.dtype not in {TensorDType.FLOAT32, TensorDType.FLOAT64}
        for item in values.values()
    ):
        return "only_float32_float64_supported"
    if any(item.mutable for item in values.values()):
        return "mutable_tensor_blocks_fusion"
    if any(
        item.operator not in _FORWARD_OPERATORS
        or item.operator_version != "0.1"
        for item in autograd.forward.instructions
    ):
        return "unsupported_forward_operator_or_version"
    if any(
        item.operator not in _BACKWARD_OPERATORS
        for item in autograd.backward
    ):
        return "unsupported_backward_operator"
    if any(
        output not in {item.result for item in autograd.forward.instructions}
        for output in autograd.forward.outputs
    ):
        return "input_as_output_requires_reference_executor"
    try:
        layouts = _value_layouts(autograd)
    except TensorCpuUnavailable as exc:
        return str(exc)
    for instruction in autograd.forward.instructions:
        if instruction.operator in {"sum", "mean"}:
            axis = instruction.attributes.get("axis")
            if axis is not None and not isinstance(axis, int):
                return "multi_axis_reduction_requires_reference_executor"
        if instruction.operator == "reshape":
            source = layouts[instruction.inputs[0]]
            if not source.contiguous:
                return "reshape_of_strided_view_requires_reference_executor"
    return None


def _select_workers(
    autograd: MetamorfoseAutogradIR,
    requested: int | str,
) -> tuple[int, dict[str, Any]]:
    available = max(1, min(4, os.cpu_count() or 1))
    largest = max(
        (
            item.output_type.numel or 0
            for item in (
                *autograd.forward.instructions,
                *autograd.backward,
            )
        ),
        default=0,
    )
    if requested == "auto":
        selected = (
            1
            if largest < 32_768
            else 2
            if largest < 262_144 or available < 4
            else 4
        )
        selected = min(selected, available)
        reason = (
            "compact_tensor_avoids_parallel_overhead"
            if selected == 1
            else "bounded_parallelism_by_largest_tensor"
        )
    else:
        try:
            selected = int(requested)
        except (TypeError, ValueError) as exc:
            raise TensorCpuError(
                "workers precisa ser auto, 1, 2 ou 4"
            ) from exc
        if selected not in {1, 2, 4}:
            raise TensorCpuError("workers precisa ser auto, 1, 2 ou 4")
        if selected > available:
            raise TensorCpuError(
                f"workers={selected} excede limite disponível {available}"
            )
        reason = "explicit_worker_budget"
    return selected, {
        "policy": "casulo-bounded-cpu-workers/0.1",
        "requested": requested,
        "selected": selected,
        "available_cap": available,
        "largest_tensor_elements": largest,
        "reason": reason,
        "allowed": [1, 2, 4],
    }


def _instruction_refs(
    autograd: MetamorfoseAutogradIR,
) -> tuple[_InstructionRef, ...]:
    references: list[_InstructionRef] = []
    global_index = 0
    for stage, instructions in (
        ("forward", autograd.forward.instructions),
        ("backward", autograd.backward),
    ):
        for stage_index, instruction in enumerate(instructions):
            references.append(
                _InstructionRef(
                    stage,
                    stage_index,
                    global_index,
                    instruction,
                )
            )
            global_index += 1
    return tuple(references)


def _all_value_types(
    autograd: MetamorfoseAutogradIR,
) -> dict[str, LarvaTensor]:
    values = {
        item.name: item.type
        for item in autograd.forward.inputs
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


def _value_layouts(
    autograd: MetamorfoseAutogradIR,
) -> dict[str, _ValueLayout]:
    layouts: dict[str, _ValueLayout] = {}
    for item in autograd.forward.inputs:
        shape = _static_shape(item.type)
        layouts[item.name] = _ValueLayout(
            item.name,
            item.type,
            shape,
            _contiguous_strides(shape),
            item.type.alias_group or f"input:{item.name}",
            False,
        )
    for instruction in autograd.forward.instructions:
        shape = _static_shape(instruction.output_type)
        if instruction.operator == "reshape":
            source = layouts[instruction.inputs[0]]
            if not source.contiguous:
                raise TensorCpuUnavailable(
                    "reshape_of_strided_view_requires_reference_executor"
                )
            layouts[instruction.result] = _ValueLayout(
                instruction.result,
                instruction.output_type,
                shape,
                _contiguous_strides(shape),
                source.alias_group,
                False,
            )
        elif instruction.operator == "transpose":
            source = layouts[instruction.inputs[0]]
            axis0, axis1 = _transpose_axes(
                len(source.shape),
                instruction.attributes,
            )
            strides = list(source.strides)
            strides[axis0], strides[axis1] = (
                strides[axis1],
                strides[axis0],
            )
            layouts[instruction.result] = _ValueLayout(
                instruction.result,
                instruction.output_type,
                shape,
                tuple(strides),
                source.alias_group,
                False,
            )
        else:
            layouts[instruction.result] = _ValueLayout(
                instruction.result,
                instruction.output_type,
                shape,
                _contiguous_strides(shape),
                instruction.output_type.alias_group
                or f"value:{instruction.result}",
                instruction.output_type.ownership
                is TensorOwnership.OWNED,
            )
    for instruction in autograd.backward:
        shape = _static_shape(instruction.output_type)
        if (
            instruction.operator == "reduce_to_shape"
            and layouts[instruction.inputs[0]].shape == shape
        ):
            source = layouts[instruction.inputs[0]]
            layouts[instruction.result] = _ValueLayout(
                instruction.result,
                instruction.output_type,
                shape,
                source.strides,
                source.alias_group,
                False,
            )
        elif instruction.operator == "transpose":
            source = layouts[instruction.inputs[0]]
            axis0, axis1 = _transpose_axes(
                len(source.shape),
                instruction.attributes,
            )
            strides = list(source.strides)
            strides[axis0], strides[axis1] = (
                strides[axis1],
                strides[axis0],
            )
            layouts[instruction.result] = _ValueLayout(
                instruction.result,
                instruction.output_type,
                shape,
                tuple(strides),
                source.alias_group,
                False,
            )
        elif instruction.operator == "reshape":
            source = layouts[instruction.inputs[0]]
            if not source.contiguous:
                raise TensorCpuUnavailable(
                    "reshape_of_strided_view_requires_reference_executor"
                )
            layouts[instruction.result] = _ValueLayout(
                instruction.result,
                instruction.output_type,
                shape,
                _contiguous_strides(shape),
                source.alias_group,
                False,
            )
        else:
            layouts[instruction.result] = _ValueLayout(
                instruction.result,
                instruction.output_type,
                shape,
                _contiguous_strides(shape),
                instruction.output_type.alias_group
                or f"gradient:{instruction.result}",
                True,
            )
    return layouts


def _form_algebra_kernels(
    autograd: MetamorfoseAutogradIR,
    layouts: Mapping[str, _ValueLayout],
    provider: GemmProviderDescriptor,
) -> tuple[CrisalidaGemmPlan, ...]:
    kernels: list[CrisalidaGemmPlan] = []
    for reference in _instruction_refs(autograd):
        instruction = reference.instruction
        if instruction.operator != "matmul":
            continue
        left = layouts[instruction.inputs[0]]
        right = layouts[instruction.inputs[1]]
        output = layouts[instruction.result]
        kernels.append(
            form_gemm_plan(
                dtype=output.tensor.dtype.value,
                left_shape=left.shape,
                right_shape=right.shape,
                left_strides=left.strides,
                right_strides=right.strides,
                output_strides=output.strides,
                provider=provider,
            )
        )
    return tuple(kernels)


def _resolve_provider_choice(
    provider: TensorCpuProviderChoice,
) -> GemmProviderDescriptor:
    if isinstance(provider, GemmProviderDescriptor):
        return provider
    if provider == "owned":
        return CASULO_OWNED_GEMM_PROVIDER
    if provider == "openblas":
        try:
            return discover_numpy_openblas_provider()
        except CasuloLinearAlgebraError as exc:
            raise TensorCpuUnavailable(str(exc)) from exc
    raise TensorCpuError(
        "provider precisa ser owned, openblas ou GemmProviderDescriptor"
    )


def _select_gemm_workers(
    workers: int,
    requested: int | str | None,
    provider: GemmProviderDescriptor,
) -> tuple[int, str]:
    if requested == "adaptive":
        return workers, "shape-adaptive-flop-thresholds/0.1"
    selected = workers if requested is None else int(requested)
    if selected not in {1, 2, 4}:
        raise TensorCpuError("gemm_workers precisa ser 1, 2 ou 4")
    if selected > workers:
        raise TensorCpuError(
            "gemm_workers não pode exceder o orçamento de workers"
        )
    if not provider.external and selected != workers:
        raise TensorCpuError(
            "provedor próprio usa o mesmo orçamento de workers"
        )
    return selected, "fixed-explicit/0.1"


def _schedule_gemm_workers(
    kernels: Sequence[CrisalidaGemmPlan],
    *,
    maximum_workers: int,
    policy: str,
) -> tuple[int, ...]:
    if policy != "shape-adaptive-flop-thresholds/0.1":
        return tuple(maximum_workers for _ in kernels)
    schedule: list[int] = []
    for kernel in kernels:
        scalar_flops = int(kernel.traffic.scalar_flops)
        rows, columns = kernel.contract.output_shape
        useful_axes = min(rows, columns)
        selected = (
            4
            if maximum_workers >= 4
            and scalar_flops >= 8_000_000
            and useful_axes >= 32
            else 2
            if maximum_workers >= 2
            and scalar_flops >= 2_000_000
            and useful_axes >= 16
            else 1
        )
        schedule.append(selected)
    return tuple(schedule)


def _plan_arena(
    layouts: Mapping[str, _ValueLayout],
    instructions: Sequence[_InstructionRef],
) -> tuple[tuple[TensorCpuBuffer, ...], int]:
    definitions: dict[str, int] = {}
    last_uses: dict[str, int] = {}
    group_values: dict[str, list[str]] = {}
    group_sizes: dict[str, int] = {}

    for reference in instructions:
        layout = layouts[reference.instruction.result]
        group_values.setdefault(layout.alias_group, []).append(layout.name)
        group_sizes[layout.alias_group] = max(
            group_sizes.get(layout.alias_group, 0),
            layout.tensor.nbytes or 0,
        )
        if layout.allocated:
            definitions.setdefault(
                layout.alias_group,
                reference.global_index,
            )
            last_uses.setdefault(
                layout.alias_group,
                reference.global_index,
            )
        for name in reference.instruction.inputs:
            source_group = layouts[name].alias_group
            if source_group in definitions:
                last_uses[source_group] = max(
                    last_uses[source_group],
                    reference.global_index,
                )

    intervals = sorted(
        (
            (
                start,
                last_uses[group],
                group,
                _align(group_sizes[group], TENSOR_CPU_ALIGNMENT),
            )
            for group, start in definitions.items()
        ),
        key=lambda item: (item[0], item[2]),
    )
    active: list[tuple[int, int, int, str]] = []
    free: list[tuple[int, int]] = []
    cursor = 0
    buffers: list[TensorCpuBuffer] = []
    for start, end, group, slot_bytes in intervals:
        remaining: list[tuple[int, int, int, str]] = []
        for active_end, offset, active_bytes, active_group in active:
            if active_end < start:
                free.append((offset, active_bytes))
            else:
                remaining.append(
                    (active_end, offset, active_bytes, active_group)
                )
        active = remaining
        candidates = sorted(
            (
                (size, offset, index)
                for index, (offset, size) in enumerate(free)
                if size >= slot_bytes
            )
        )
        if candidates:
            chosen_size, offset, free_index = candidates[0]
            free.pop(free_index)
            allocated_slot = chosen_size
        else:
            offset = _align(cursor, TENSOR_CPU_ALIGNMENT)
            allocated_slot = slot_bytes
            cursor = offset + allocated_slot
        active.append((end, offset, allocated_slot, group))
        buffers.append(
            TensorCpuBuffer(
                alias_group=group,
                offset=offset,
                nbytes=group_sizes[group],
                slot_bytes=allocated_slot,
                first_instruction=start,
                last_instruction=end,
                values=tuple(sorted(group_values.get(group, ()))),
            )
        )
    required = max(
        (item.offset + item.slot_bytes for item in buffers),
        default=0,
    )
    return tuple(buffers), required


def _fusion_regions(
    autograd: MetamorfoseAutogradIR,
    layouts: Mapping[str, _ValueLayout],
) -> tuple[TensorCpuFusionRegion, ...]:
    regions: list[TensorCpuFusionRegion] = []
    for stage, instructions in (
        ("forward", autograd.forward.instructions),
        ("backward", autograd.backward),
    ):
        current: list[TensorIRInstruction | AutogradInstruction] = []
        first = 0
        for index, instruction in enumerate(instructions):
            layout = layouts[instruction.result]
            compatible = (
                instruction.operator in _POINTWISE_OPERATORS
                and (
                    not current
                    or (
                        layout.shape
                        == layouts[current[0].result].shape
                        and layout.tensor.dtype
                        is layouts[current[0].result].tensor.dtype
                    )
                )
            )
            if compatible:
                if not current:
                    first = index
                current.append(instruction)
                continue
            if current:
                regions.append(
                    _make_region(stage, first, current, layouts)
                )
                current = []
            if instruction.operator in _POINTWISE_OPERATORS:
                first = index
                current = [instruction]
        if current:
            regions.append(_make_region(stage, first, current, layouts))
    return tuple(regions)


def _make_region(
    stage: str,
    first: int,
    instructions: Sequence[TensorIRInstruction | AutogradInstruction],
    layouts: Mapping[str, _ValueLayout],
) -> TensorCpuFusionRegion:
    output = layouts[instructions[0].result]
    vectorizable = all(
        layouts[name].shape == output.shape
        and layouts[name].contiguous
        for instruction in instructions
        for name in instruction.inputs
    )
    return TensorCpuFusionRegion(
        stage=stage,
        first_instruction=first,
        last_instruction=first + len(instructions) - 1,
        operators=tuple(item.operator for item in instructions),
        results=tuple(item.result for item in instructions),
        dtype=output.tensor.dtype.value,
        shape=output.shape,
        vectorizable=vectorizable,
    )


def generate_tensor_cpu_artifact(
    autograd: MetamorfoseAutogradIR,
    *,
    plan: TensorCpuPlan | None = None,
    arena_budget_bytes: int = DEFAULT_ARENA_BUDGET_BYTES,
    workers: int | str = "auto",
) -> TensorCpuArtifact:
    active_plan = plan or plan_tensor_cpu(
        autograd,
        arena_budget_bytes=arena_budget_bytes,
        workers=workers,
    )
    if not active_plan.eligible:
        raise TensorCpuUnavailable(
            active_plan.reason or "grafo inelegível para backend CPU"
        )
    source = _render_tensor_cpu_source(autograd, active_plan)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return TensorCpuArtifact(
        protocol=TENSOR_CPU_ABI_PROTOCOL,
        backend=TENSOR_CPU_BACKEND,
        graph_sha256=active_plan.graph_sha256,
        source=source,
        source_sha256=source_sha256,
        plan=active_plan,
    )


def _render_tensor_cpu_source(
    autograd: MetamorfoseAutogradIR,
    plan: TensorCpuPlan,
) -> str:
    layouts = _value_layouts(autograd)
    gemm_provider = (
        plan.algebra_kernels[0].provider
        if plan.algebra_kernels
        else CASULO_OWNED_GEMM_PROVIDER
    )
    if any(
        kernel.provider != gemm_provider
        for kernel in plan.algebra_kernels
    ):
        raise TensorCpuError("plano mistura provedores GEMM")
    buffer_by_group = {
        item.alias_group: item
        for item in plan.buffers
    }
    forward_observations = {
        item.result: index
        for index, item in enumerate(autograd.forward.instructions)
    }
    gradient_observations = {
        item.value: len(autograd.forward.instructions) + index
        for index, item in enumerate(autograd.gradients)
    }
    observation_map = {
        **forward_observations,
        **gradient_observations,
    }
    mandatory_observations = {
        *autograd.forward.outputs,
        *(item.value for item in autograd.gradients),
    }
    matmul_results = [
        reference.instruction.result
        for reference in _instruction_refs(autograd)
        if reference.instruction.operator == "matmul"
    ]
    if len(matmul_results) != len(plan.gemm_worker_schedule):
        raise TensorCpuError(
            "agenda de workers GEMM diverge das instruções matmul"
        )
    gemm_workers_by_result = dict(
        zip(matmul_results, plan.gemm_worker_schedule)
    )
    lines = [
        "/* Generated by Casulo/T. Deterministic C99 tensor backend. */",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "#include <math.h>",
        "",
        "#if defined(_WIN32)",
        "#define CASULO_EXPORT __declspec(dllexport)",
        "#else",
        "#define CASULO_EXPORT __attribute__((visibility(\"default\")))",
        "#endif",
        "",
        f"static const char *CASULO_TENSOR_CPU_ABI = "
        f"\"{TENSOR_CPU_ABI_PROTOCOL}\";",
        f"static const char *CASULO_TENSOR_CPU_BACKEND = "
        f"\"{TENSOR_CPU_BACKEND}\";",
        f"static const char *CASULO_TENSOR_GRAPH_SHA256 = "
        f"\"{plan.graph_sha256}\";",
        f"static const char *CASULO_GEMM_PROVIDER_ID = "
        f"\"{gemm_provider.provider_id}\";",
        f"static const char *CASULO_GEMM_PROVIDER_BINARY_SHA256 = "
        f"\"{gemm_provider.binary_sha256 or ''}\";",
        "",
        "typedef void (*casulo_sgemm64_fn)(",
        "    int, int, int, int64_t, int64_t, int64_t, float,",
        "    const float *, int64_t, const float *, int64_t,",
        "    float, float *, int64_t);",
        "typedef void (*casulo_dgemm64_fn)(",
        "    int, int, int, int64_t, int64_t, int64_t, double,",
        "    const double *, int64_t, const double *, int64_t,",
        "    double, double *, int64_t);",
        "typedef void (*casulo_set_threads_fn)(int);",
        "static casulo_sgemm64_fn CASULO_EXTERNAL_SGEMM = NULL;",
        "static casulo_dgemm64_fn CASULO_EXTERNAL_DGEMM = NULL;",
        "static casulo_set_threads_fn CASULO_EXTERNAL_SET_THREADS = NULL;",
        "",
        *_render_c_helpers(),
        "",
    ]
    for name in _ordered_value_names(autograd):
        layout = layouts[name]
        identifier = _c_name(name)
        lines.append(
            f"static const size_t shape_{identifier}[{len(layout.shape)}] = "
            "{" + ", ".join(str(item) for item in layout.shape) + "};"
        )
        lines.append(
            f"static const size_t stride_{identifier}[{len(layout.strides)}] = "
            "{" + ", ".join(str(item) for item in layout.strides) + "};"
        )
    lines.extend(
        [
            "",
            "CASULO_EXPORT const char *casulo_tensor_cpu_abi(void) {",
            "  return CASULO_TENSOR_CPU_ABI;",
            "}",
            "",
            "CASULO_EXPORT const char *casulo_tensor_cpu_backend(void) {",
            "  return CASULO_TENSOR_CPU_BACKEND;",
            "}",
            "",
            "CASULO_EXPORT const char *casulo_tensor_graph_sha256(void) {",
            "  return CASULO_TENSOR_GRAPH_SHA256;",
            "}",
            "",
            "CASULO_EXPORT const char *casulo_gemm_provider_id(void) {",
            "  return CASULO_GEMM_PROVIDER_ID;",
            "}",
            "",
            "CASULO_EXPORT const char *casulo_gemm_provider_binary_sha256(void) {",
            "  return CASULO_GEMM_PROVIDER_BINARY_SHA256;",
            "}",
            "",
            "CASULO_EXPORT int casulo_tensor_bind_gemm_provider(",
            "    void *float32_kernel, void *float64_kernel,",
            "    void *set_threads) {",
            "  CASULO_EXTERNAL_SGEMM = (casulo_sgemm64_fn)float32_kernel;",
            "  CASULO_EXTERNAL_DGEMM = (casulo_dgemm64_fn)float64_kernel;",
            "  CASULO_EXTERNAL_SET_THREADS = "
            "(casulo_set_threads_fn)set_threads;",
            "  return 0;",
            "}",
            "",
            "CASULO_EXPORT int casulo_tensor_execute(",
            "    const void *const *inputs,",
            "    void *const *observed,",
            "    void *arena,",
            "    size_t arena_bytes,",
            "    int workers,",
            "    int audit) {",
            "  if (inputs == NULL || observed == NULL || arena == NULL) return 2;",
            "  if (workers != 1 && workers != 2 && workers != 4) return 3;",
            (
                "  if (CASULO_EXTERNAL_SGEMM == NULL || "
                "CASULO_EXTERNAL_DGEMM == NULL || "
                "CASULO_EXTERNAL_SET_THREADS == NULL) return 4;"
                if gemm_provider.external
                else "  /* provedor GEMM próprio não requer binding */"
            ),
            f"  if (arena_bytes < {plan.arena_required_bytes or 0}u) return 1;",
            "  unsigned char *arena_base = (unsigned char *)arena;",
        ]
    )
    group_pointer: dict[str, str] = {}
    for index, item in enumerate(autograd.forward.inputs):
        layout = layouts[item.name]
        pointer = f"v_{_c_name(item.name)}"
        lines.append(
            f"  {_c_type(layout.tensor.dtype)} *{pointer} = "
            f"({_c_type(layout.tensor.dtype)} *)inputs[{index}];"
        )
        group_pointer.setdefault(layout.alias_group, pointer)
    for reference in _instruction_refs(autograd):
        name = reference.instruction.result
        layout = layouts[name]
        pointer = f"v_{_c_name(name)}"
        buffer = buffer_by_group.get(layout.alias_group)
        if buffer is not None and layout.allocated:
            lines.append(
                f"  {_c_type(layout.tensor.dtype)} *{pointer} = "
                f"({_c_type(layout.tensor.dtype)} *)(arena_base + "
                f"{buffer.offset}u);"
            )
            group_pointer.setdefault(layout.alias_group, pointer)
        else:
            source_pointer = group_pointer.get(layout.alias_group)
            if source_pointer is None:
                raise TensorCpuError(
                    f"grupo de alias sem origem: {layout.alias_group}"
                )
            lines.append(
                f"  {_c_type(layout.tensor.dtype)} *{pointer} = "
                f"({ _c_type(layout.tensor.dtype) } *){source_pointer};"
            )
    lines.append("")

    region_by_start = {
        (item.stage, item.first_instruction): item
        for item in plan.fusion_regions
    }
    for stage, instructions in (
        ("forward", autograd.forward.instructions),
        ("backward", autograd.backward),
    ):
        lines.append(f"  /* {stage} */")
        index = 0
        while index < len(instructions):
            region = region_by_start.get((stage, index))
            if region is not None:
                selected = instructions[
                    region.first_instruction : region.last_instruction + 1
                ]
                lines.extend(
                    _render_pointwise_region(
                        selected,
                        region,
                        layouts,
                        observation_map,
                        mandatory_observations,
                    )
                )
                index = region.last_instruction + 1
                continue
            instruction = instructions[index]
            lines.extend(
                _render_nonpointwise_instruction(
                    instruction,
                    stage,
                    layouts,
                    observation_map,
                    mandatory_observations,
                    gemm_provider,
                    gemm_workers_by_result.get(
                        instruction.result,
                        plan.gemm_workers,
                    ),
                )
            )
            index += 1
        lines.append("")
    lines.extend(["  return 0;", "}", ""])
    return "\n".join(lines)


def _render_c_helpers() -> list[str]:
    return [
        "static size_t casulo_offset(",
        "    size_t flat, int rank, const size_t *shape,",
        "    const size_t *strides) {",
        "  size_t offset = 0;",
        "  for (int axis = rank - 1; axis >= 0; --axis) {",
        "    size_t coordinate = flat % shape[axis];",
        "    flat /= shape[axis];",
        "    offset += coordinate * strides[axis];",
        "  }",
        "  return offset;",
        "}",
        "",
        "static size_t casulo_broadcast_offset(",
        "    size_t flat, int output_rank, const size_t *output_shape,",
        "    int input_rank, const size_t *input_shape,",
        "    const size_t *input_strides) {",
        "  size_t offset = 0;",
        "  int shift = output_rank - input_rank;",
        "  for (int axis = output_rank - 1; axis >= 0; --axis) {",
        "    size_t coordinate = flat % output_shape[axis];",
        "    flat /= output_shape[axis];",
        "    int input_axis = axis - shift;",
        "    if (input_axis >= 0 && input_shape[input_axis] != 1u) {",
        "      offset += coordinate * input_strides[input_axis];",
        "    }",
        "  }",
        "  return offset;",
        "}",
        "",
        "static size_t casulo_reduce_target_offset(",
        "    size_t flat, int source_rank, const size_t *source_shape,",
        "    int target_rank, const size_t *target_shape,",
        "    const size_t *target_strides) {",
        "  size_t offset = 0;",
        "  int shift = source_rank - target_rank;",
        "  for (int axis = source_rank - 1; axis >= 0; --axis) {",
        "    size_t coordinate = flat % source_shape[axis];",
        "    flat /= source_shape[axis];",
        "    int target_axis = axis - shift;",
        "    if (target_axis >= 0 && target_shape[target_axis] != 1u) {",
        "      offset += coordinate * target_strides[target_axis];",
        "    }",
        "  }",
        "  return offset;",
        "}",
        "",
        "static size_t casulo_reduction_output_offset(",
        "    size_t flat, int input_rank, const size_t *input_shape,",
        "    int axis, int keepdim, const size_t *output_strides) {",
        "  size_t offset = 0;",
        "  for (int input_axis = input_rank - 1; input_axis >= 0; --input_axis) {",
        "    size_t coordinate = flat % input_shape[input_axis];",
        "    flat /= input_shape[input_axis];",
        "    if (input_axis == axis) continue;",
        "    int output_axis = keepdim ? input_axis : "
        "(input_axis < axis ? input_axis : input_axis - 1);",
        "    offset += coordinate * output_strides[output_axis];",
        "  }",
        "  return offset;",
        "}",
        "",
        "static size_t casulo_backward_gradient_offset(",
        "    size_t flat, int source_rank, const size_t *source_shape,",
        "    int axis, int keepdim, const size_t *gradient_strides) {",
        "  if (axis < 0) return 0u;",
        "  size_t offset = 0;",
        "  for (int source_axis = source_rank - 1; source_axis >= 0; --source_axis) {",
        "    size_t coordinate = flat % source_shape[source_axis];",
        "    flat /= source_shape[source_axis];",
        "    if (source_axis == axis) continue;",
        "    int gradient_axis = keepdim ? source_axis : "
        "(source_axis < axis ? source_axis : source_axis - 1);",
        "    offset += coordinate * gradient_strides[gradient_axis];",
        "  }",
        "  return offset;",
        "}",
        "",
        "static size_t casulo_transpose_source_offset(",
        "    size_t flat, int rank, const size_t *output_shape,",
        "    int axis0, int axis1, const size_t *source_strides) {",
        "  size_t coordinates[4] = {0u, 0u, 0u, 0u};",
        "  for (int axis = rank - 1; axis >= 0; --axis) {",
        "    coordinates[axis] = flat % output_shape[axis];",
        "    flat /= output_shape[axis];",
        "  }",
        "  size_t temporary = coordinates[axis0];",
        "  coordinates[axis0] = coordinates[axis1];",
        "  coordinates[axis1] = temporary;",
        "  size_t offset = 0;",
        "  for (int axis = 0; axis < rank; ++axis) {",
        "    offset += coordinates[axis] * source_strides[axis];",
        "  }",
        "  return offset;",
        "}",
    ]


def _render_pointwise_region(
    instructions: Sequence[TensorIRInstruction | AutogradInstruction],
    region: TensorCpuFusionRegion,
    layouts: Mapping[str, _ValueLayout],
    observations: Mapping[str, int],
    mandatory_observations: set[str],
) -> list[str]:
    output = layouts[instructions[0].result]
    count = math.prod(output.shape)
    pragma = (
        "  #pragma omp parallel for simd num_threads(workers) "
        f"if(workers > 1 && {count}u >= 32768u)"
        if region.vectorizable
        else (
            "  #pragma omp parallel for num_threads(workers) "
            f"if(workers > 1 && {count}u >= 32768u)"
        )
    )
    lines = [
        f"  /* fusion {region.stage} "
        f"{region.first_instruction}:{region.last_instruction} */",
        "  #ifdef _OPENMP",
        pragma,
        "  #endif",
        f"  for (long long linear = 0; linear < {count}ll; ++linear) {{",
    ]
    for instruction in instructions:
        expression = _pointwise_expression(instruction, layouts)
        pointer = f"v_{_c_name(instruction.result)}"
        lines.append(f"    {pointer}[linear] = {expression};")
        observation = observations.get(instruction.result)
        if observation is not None:
            ctype = _c_type(instruction.output_type.dtype)
            statement = (
                f"    (({ctype} *)observed[{observation}])[linear] = "
                f"{pointer}[linear];"
            )
            lines.append(
                statement
                if instruction.result in mandatory_observations
                else f"    if (audit) {statement.strip()}"
            )
    lines.append("  }")
    return lines


def _pointwise_expression(
    instruction: TensorIRInstruction | AutogradInstruction,
    layouts: Mapping[str, _ValueLayout],
) -> str:
    output = layouts[instruction.result]
    arguments = [
        _pointwise_input(name, output, layouts)
        for name in instruction.inputs
    ]
    operator = instruction.operator
    dtype = output.tensor.dtype
    one = "1.0f" if dtype is TensorDType.FLOAT32 else "1.0"
    zero = "0.0f" if dtype is TensorDType.FLOAT32 else "0.0"
    if operator == "ones_like":
        return one
    if operator == "zeros_like":
        return zero
    if operator == "add":
        return f"({arguments[0]} + {arguments[1]})"
    if operator == "sub":
        return f"({arguments[0]} - {arguments[1]})"
    if operator == "mul":
        return f"({arguments[0]} * {arguments[1]})"
    if operator == "div":
        return f"({arguments[0]} / {arguments[1]})"
    if operator == "neg":
        return f"(-{arguments[0]})"
    if operator == "relu":
        return f"({arguments[0]} > {zero} ? {arguments[0]} : {zero})"
    if operator == "sigmoid":
        exp_function = "expf" if dtype is TensorDType.FLOAT32 else "exp"
        return f"({one} / ({one} + {exp_function}(-{arguments[0]})))"
    if operator == "tanh":
        function = "tanhf" if dtype is TensorDType.FLOAT32 else "tanh"
        return f"{function}({arguments[0]})"
    if operator == "relu_backward":
        return (
            f"({arguments[0]} * "
            f"({arguments[1]} > {zero} ? {one} : {zero}))"
        )
    if operator == "sigmoid_backward":
        return (
            f"({arguments[0]} * {arguments[2]} * "
            f"({one} - {arguments[2]}))"
        )
    if operator == "tanh_backward":
        return (
            f"({arguments[0]} * "
            f"({one} - {arguments[2]} * {arguments[2]}))"
        )
    raise TensorCpuError(f"operador pointwise não renderizável: {operator}")


def _pointwise_input(
    name: str,
    output: _ValueLayout,
    layouts: Mapping[str, _ValueLayout],
) -> str:
    source = layouts[name]
    pointer = f"v_{_c_name(name)}"
    if source.shape == output.shape and source.contiguous:
        return f"{pointer}[linear]"
    if source.shape == output.shape:
        return (
            f"{pointer}[casulo_offset((size_t)linear, {len(source.shape)}, "
            f"shape_{_c_name(name)}, stride_{_c_name(name)})]"
        )
    return (
        f"{pointer}[casulo_broadcast_offset((size_t)linear, "
        f"{len(output.shape)}, shape_{_c_name(output.name)}, "
        f"{len(source.shape)}, shape_{_c_name(name)}, "
        f"stride_{_c_name(name)})]"
    )


def _render_nonpointwise_instruction(
    instruction: TensorIRInstruction | AutogradInstruction,
    stage: str,
    layouts: Mapping[str, _ValueLayout],
    observations: Mapping[str, int],
    mandatory_observations: set[str],
    gemm_provider: GemmProviderDescriptor,
    gemm_workers: int,
) -> list[str]:
    operator = instruction.operator
    if operator == "matmul":
        lines = _render_matmul(
            instruction,
            layouts,
            gemm_provider,
            gemm_workers,
        )
    elif operator in {"sum", "mean"}:
        lines = _render_reduction(instruction, layouts)
    elif operator == "reduce_to_shape":
        lines = _render_reduce_to_shape(instruction, layouts)
    elif operator in {"sum_backward", "mean_backward"}:
        lines = _render_reduction_backward(instruction, layouts)
    elif operator == "reshape":
        lines = _render_reshape(instruction, stage, layouts)
    elif operator == "transpose":
        lines = _render_transpose(instruction, stage, layouts)
    else:
        raise TensorCpuError(
            f"operador não pointwise não renderizável: {operator}"
        )
    observation = observations.get(instruction.result)
    if observation is not None:
        lines.extend(
            _render_observation_copy(
                instruction.result,
                observation,
                layouts,
                instruction.result in mandatory_observations,
            )
        )
    return lines


def _render_matmul(
    instruction: TensorIRInstruction | AutogradInstruction,
    layouts: Mapping[str, _ValueLayout],
    provider: GemmProviderDescriptor,
    gemm_workers: int,
) -> list[str]:
    left = layouts[instruction.inputs[0]]
    right = layouts[instruction.inputs[1]]
    output = layouts[instruction.result]
    if len(left.shape) != 2 or len(right.shape) != 2:
        raise TensorCpuError("matmul CPU 0.1 exige rank 2")
    rows, inner = left.shape
    _, columns = right.shape
    ctype = _c_type(output.tensor.dtype)
    left_pointer = f"v_{_c_name(left.name)}"
    right_pointer = f"v_{_c_name(right.name)}"
    output_pointer = f"v_{_c_name(output.name)}"
    algebra = form_gemm_plan(
        dtype=output.tensor.dtype.value,
        left_shape=left.shape,
        right_shape=right.shape,
        left_strides=left.strides,
        right_strides=right.strides,
        output_strides=output.strides,
        provider=provider,
    )
    if provider.external:
        return _render_external_gemm(
            algebra,
            left_pointer=left_pointer,
            right_pointer=right_pointer,
            output_pointer=output_pointer,
            gemm_workers=gemm_workers,
        )
    prefix = [
        f"  /* {instruction.result} = matmul; "
        f"Casulo {algebra.loop_order}; {algebra.identity} */",
        "  #ifdef _OPENMP",
        f"  #pragma omp parallel for num_threads({gemm_workers}) "
        f"if({gemm_workers} > 1)",
        "  #endif",
        f"  for (long long row = 0; row < {rows}ll; ++row) {{",
    ]
    if algebra.loop_order == "row-inner-column":
        return [
            *prefix,
            f"    for (size_t column = 0; column < {columns}u; ++column) "
            f"{output_pointer}[row * {columns}u + column] = ({ctype})0;",
            f"    for (size_t inner = 0; inner < {inner}u; ++inner) {{",
            f"      const {ctype} left_value = {left_pointer}[row * "
            f"{left.strides[0]}u + inner * {left.strides[1]}u];",
            "      #ifdef _OPENMP",
            "      #pragma omp simd",
            "      #endif",
            f"      for (size_t column = 0; column < {columns}u; ++column) {{",
            f"        {output_pointer}[row * {columns}u + column] += "
            f"left_value * {right_pointer}[inner * {right.strides[0]}u + "
            f"column * {right.strides[1]}u];",
            "      }",
            "    }",
            "  }",
        ]
    return [
        *prefix,
        f"    for (size_t column = 0; column < {columns}u; ++column) {{",
        f"      {ctype} accumulator = ({ctype})0;",
        f"      for (size_t inner = 0; inner < {inner}u; ++inner) {{",
        f"        accumulator += {left_pointer}[row * "
        f"{left.strides[0]}u + inner * {left.strides[1]}u] * "
        f"{right_pointer}[inner * {right.strides[0]}u + column * "
        f"{right.strides[1]}u];",
        "      }",
        f"      {output_pointer}[row * {columns}u + column] = accumulator;",
        "    }",
        "  }",
    ]


def _render_external_gemm(
    algebra: CrisalidaGemmPlan,
    *,
    left_pointer: str,
    right_pointer: str,
    output_pointer: str,
    gemm_workers: int,
) -> list[str]:
    contract = algebra.contract
    rows, inner = contract.left_shape
    _, columns = contract.right_shape
    left_transpose, left_leading = _cblas_layout(
        contract.left_shape,
        contract.left_strides,
    )
    right_transpose, right_leading = _cblas_layout(
        contract.right_shape,
        contract.right_strides,
    )
    if contract.output_strides != (columns, 1):
        raise TensorCpuUnavailable(
            "CBLAS exige saída row-major contígua"
        )
    function = (
        "CASULO_EXTERNAL_SGEMM"
        if contract.dtype == "float32"
        else "CASULO_EXTERNAL_DGEMM"
    )
    scalar = "1.0f" if contract.dtype == "float32" else "1.0"
    zero = "0.0f" if contract.dtype == "float32" else "0.0"
    return [
        f"  /* external GEMM; {algebra.provider.provider_id}; "
        f"{algebra.identity}; workers={gemm_workers} */",
        f"  CASULO_EXTERNAL_SET_THREADS({gemm_workers});",
        f"  {function}(101, {left_transpose}, {right_transpose},",
        f"      {rows}ll, {columns}ll, {inner}ll, {scalar},",
        f"      {left_pointer}, {left_leading}ll,",
        f"      {right_pointer}, {right_leading}ll,",
        f"      {zero}, {output_pointer}, {columns}ll);",
    ]


def _cblas_layout(
    shape: tuple[int, int],
    strides: tuple[int, int],
) -> tuple[int, int]:
    rows, columns = shape
    if strides == (columns, 1):
        return 111, columns
    if strides == (1, rows):
        return 112, rows
    raise TensorCpuUnavailable(
        f"CBLAS não representa strides {strides} para shape {shape}"
    )


def _render_reduction(
    instruction: TensorIRInstruction | AutogradInstruction,
    layouts: Mapping[str, _ValueLayout],
) -> list[str]:
    source = layouts[instruction.inputs[0]]
    output = layouts[instruction.result]
    source_pointer = f"v_{_c_name(source.name)}"
    output_pointer = f"v_{_c_name(output.name)}"
    source_count = math.prod(source.shape)
    output_count = math.prod(output.shape)
    axis_value = instruction.attributes.get("axis")
    keepdim = bool(instruction.attributes.get("keepdim", False))
    divisor = (
        source_count
        if axis_value is None
        else source.shape[_normalize_axis(int(axis_value), len(source.shape))]
    )
    ctype = _c_type(output.tensor.dtype)
    lines = [
        f"  /* {instruction.result} = {instruction.operator} */",
        f"  for (size_t linear = 0; linear < {output_count}u; ++linear) "
        f"{output_pointer}[linear] = ({ctype})0;",
    ]
    if axis_value is None:
        source_expression = (
            f"{source_pointer}[linear]"
            if source.contiguous
            else (
                f"{source_pointer}[casulo_offset(linear, "
                f"{len(source.shape)}, shape_{_c_name(source.name)}, "
                f"stride_{_c_name(source.name)})]"
            )
        )
        lines.extend(
            [
                f"  for (size_t linear = 0; linear < {source_count}u; "
                "++linear) {",
                f"    {output_pointer}[0] += {source_expression};",
                "  }",
            ]
        )
    else:
        axis = _normalize_axis(int(axis_value), len(source.shape))
        lines.extend(
            [
                f"  for (size_t linear = 0; linear < {source_count}u; "
                "++linear) {",
                "    size_t output_offset = casulo_reduction_output_offset(",
                f"        linear, {len(source.shape)}, "
                f"shape_{_c_name(source.name)}, {axis}, "
                f"{1 if keepdim else 0}, stride_{_c_name(output.name)});",
                f"    {output_pointer}[output_offset] += "
                f"{source_pointer}[casulo_offset(linear, "
                f"{len(source.shape)}, shape_{_c_name(source.name)}, "
                f"stride_{_c_name(source.name)})];",
                "  }",
            ]
        )
    if instruction.operator == "mean":
        lines.extend(
            [
                f"  for (size_t linear = 0; linear < {output_count}u; "
                "++linear) {",
                f"    {output_pointer}[linear] /= ({ctype}){divisor};",
                "  }",
            ]
        )
    return lines


def _render_reduce_to_shape(
    instruction: TensorIRInstruction | AutogradInstruction,
    layouts: Mapping[str, _ValueLayout],
) -> list[str]:
    source = layouts[instruction.inputs[0]]
    target = layouts[instruction.inputs[1]]
    output = layouts[instruction.result]
    source_pointer = f"v_{_c_name(source.name)}"
    output_pointer = f"v_{_c_name(output.name)}"
    source_count = math.prod(source.shape)
    output_count = math.prod(output.shape)
    ctype = _c_type(output.tensor.dtype)
    if not output.allocated:
        return [
            f"  /* {instruction.result} = reduce_to_shape identity; "
            "zero-copy */"
        ]
    return [
        f"  /* {instruction.result} = reduce_to_shape */",
        f"  for (size_t linear = 0; linear < {output_count}u; ++linear) "
        f"{output_pointer}[linear] = ({ctype})0;",
        f"  for (size_t linear = 0; linear < {source_count}u; ++linear) {{",
        "    size_t target_offset = casulo_reduce_target_offset(",
        f"        linear, {len(source.shape)}, "
        f"shape_{_c_name(source.name)}, {len(target.shape)}, "
        f"shape_{_c_name(target.name)}, stride_{_c_name(output.name)});",
        f"    {output_pointer}[target_offset] += "
        f"{source_pointer}[casulo_offset(linear, {len(source.shape)}, "
        f"shape_{_c_name(source.name)}, stride_{_c_name(source.name)})];",
        "  }",
    ]


def _render_reduction_backward(
    instruction: TensorIRInstruction | AutogradInstruction,
    layouts: Mapping[str, _ValueLayout],
) -> list[str]:
    gradient = layouts[instruction.inputs[0]]
    source = layouts[instruction.inputs[1]]
    output = layouts[instruction.result]
    gradient_pointer = f"v_{_c_name(gradient.name)}"
    output_pointer = f"v_{_c_name(output.name)}"
    output_count = math.prod(output.shape)
    axis_value = instruction.attributes.get("axis")
    axis = (
        -1
        if axis_value is None
        else _normalize_axis(int(axis_value), len(source.shape))
    )
    keepdim = bool(instruction.attributes.get("keepdim", False))
    divisor = (
        math.prod(source.shape)
        if axis < 0
        else source.shape[axis]
    )
    ctype = _c_type(output.tensor.dtype)
    lines = [
        f"  /* {instruction.result} = {instruction.operator} */",
        "  #ifdef _OPENMP",
        "  #pragma omp parallel for simd num_threads(workers) "
        f"if(workers > 1 && {output_count}u >= 32768u)",
        "  #endif",
        f"  for (long long linear = 0; linear < {output_count}ll; "
        "++linear) {",
        "    size_t gradient_offset = casulo_backward_gradient_offset(",
        f"        (size_t)linear, {len(source.shape)}, "
        f"shape_{_c_name(source.name)}, {axis}, "
        f"{1 if keepdim else 0}, stride_{_c_name(gradient.name)});",
        f"    {output_pointer}[linear] = "
        f"{gradient_pointer}[gradient_offset];",
    ]
    if instruction.operator == "mean_backward":
        lines.append(
            f"    {output_pointer}[linear] /= ({ctype}){divisor};"
        )
    lines.append("  }")
    return lines


def _render_reshape(
    instruction: TensorIRInstruction | AutogradInstruction,
    stage: str,
    layouts: Mapping[str, _ValueLayout],
) -> list[str]:
    if not layouts[instruction.result].allocated:
        return [f"  /* {instruction.result} = reshape view; zero-copy */"]
    source = layouts[instruction.inputs[0]]
    output = layouts[instruction.result]
    source_pointer = f"v_{_c_name(source.name)}"
    output_pointer = f"v_{_c_name(output.name)}"
    count = math.prod(output.shape)
    return [
        f"  /* {instruction.result} = reshape materialized */",
        "  #ifdef _OPENMP",
        "  #pragma omp parallel for simd num_threads(workers) "
        f"if(workers > 1 && {count}u >= 32768u)",
        "  #endif",
        f"  for (long long linear = 0; linear < {count}ll; ++linear) {{",
        f"    {output_pointer}[linear] = "
        f"{source_pointer}[casulo_offset((size_t)linear, "
        f"{len(source.shape)}, shape_{_c_name(source.name)}, "
        f"stride_{_c_name(source.name)})];",
        "  }",
    ]


def _render_transpose(
    instruction: TensorIRInstruction | AutogradInstruction,
    stage: str,
    layouts: Mapping[str, _ValueLayout],
) -> list[str]:
    if not layouts[instruction.result].allocated:
        return [f"  /* {instruction.result} = transpose view; zero-copy */"]
    source = layouts[instruction.inputs[0]]
    output = layouts[instruction.result]
    axis0, axis1 = _transpose_axes(
        len(source.shape),
        instruction.attributes,
    )
    source_pointer = f"v_{_c_name(source.name)}"
    output_pointer = f"v_{_c_name(output.name)}"
    count = math.prod(output.shape)
    return [
        f"  /* {instruction.result} = transpose materialized */",
        "  #ifdef _OPENMP",
        "  #pragma omp parallel for simd num_threads(workers) "
        f"if(workers > 1 && {count}u >= 32768u)",
        "  #endif",
        f"  for (long long linear = 0; linear < {count}ll; ++linear) {{",
        f"    size_t source_offset = casulo_transpose_source_offset(",
        f"        (size_t)linear, {len(output.shape)}, "
        f"shape_{_c_name(output.name)}, {axis0}, {axis1}, "
        f"stride_{_c_name(source.name)});",
        f"    {output_pointer}[linear] = {source_pointer}[source_offset];",
        "  }",
    ]


def _render_observation_copy(
    name: str,
    observation: int,
    layouts: Mapping[str, _ValueLayout],
    mandatory: bool,
) -> list[str]:
    layout = layouts[name]
    pointer = f"v_{_c_name(name)}"
    count = math.prod(layout.shape)
    ctype = _c_type(layout.tensor.dtype)
    source = (
        f"{pointer}[linear]"
        if layout.contiguous
        else (
            f"{pointer}[casulo_offset((size_t)linear, "
            f"{len(layout.shape)}, shape_{_c_name(name)}, "
            f"stride_{_c_name(name)})]"
        )
    )
    lines = [
        "  #ifdef _OPENMP",
        "  #pragma omp parallel for simd num_threads(workers) "
        f"if(workers > 1 && {count}u >= 32768u)",
        "  #endif",
        f"  for (long long linear = 0; linear < {count}ll; ++linear) {{",
        f"    (({ctype} *)observed[{observation}])[linear] = {source};",
        "  }",
    ]
    if mandatory:
        return lines
    return [
        "  if (audit) {",
        *(f"  {line}" for line in lines),
        "  }",
    ]


def compile_tensor_cpu_artifact(
    artifact: TensorCpuArtifact,
) -> TensorCpuBuild:
    compiler = _find_compiler()
    compiler_version = _compiler_version(compiler)
    compiler_name = compiler.name.lower()
    if "gcc" not in compiler_name and "clang" not in compiler_name:
        raise TensorCpuUnavailable(
            "backend tensorial 0.1 exige GCC ou Clang com OpenMP"
        )
    cache_key = hashlib.sha256(
        (
            artifact.source_sha256
            + compiler_version
            + platform.machine()
            + platform.processor()
            + TENSOR_CPU_BACKEND
        ).encode("utf-8")
    ).hexdigest()[:24]
    cache_root = Path(
        os.environ.get(
            "CASULO_NATIVE_CACHE",
            str(Path.home() / ".casulo-native"),
        )
    ).expanduser()
    target = cache_root / "tensor-cpu" / cache_key
    target.mkdir(parents=True, exist_ok=True)
    source = target / "casulo_tensor_cpu.c"
    library = target / (
        "casulo_tensor_cpu.dll"
        if os.name == "nt"
        else (
            "libcasulo_tensor_cpu.dylib"
            if platform.system() == "Darwin"
            else "libcasulo_tensor_cpu.so"
        )
    )
    vector_report = target / "vectorization.txt"
    manifest_path = target / "build.json"
    command = [
        str(compiler),
        "-std=c99",
        "-O3",
        "-march=native",
        "-fno-fast-math",
        "-ffp-contract=fast",
        "-fopenmp",
        "-shared",
    ]
    if os.name != "nt":
        command.extend(["-fPIC", "-fvisibility=hidden"])
    else:
        command.extend(
            ["-Wl,--no-insert-timestamp,--image-base,0x180000000", "-s"]
        )
    if "gcc" in compiler_name:
        command.append(f"-fopt-info-vec-optimized={vector_report}")
    command.extend([str(source), "-o", str(library), "-lm"])

    cache_hit = False
    if source.is_file() and manifest_path.is_file() and library.is_file():
        try:
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            cache_hit = (
                source.read_text(encoding="utf-8") == artifact.source
                and saved.get("protocol") == TENSOR_CPU_BUILD_PROTOCOL
                and saved.get("source_sha256") == artifact.source_sha256
                and saved.get("compiler_version") == compiler_version
                and saved.get("binary_sha256") == _file_sha256(library)
            )
        except (OSError, ValueError, json.JSONDecodeError):
            cache_hit = False

    compilation_wall_ns: int | None = None
    if not cache_hit:
        source.write_text(
            artifact.source,
            encoding="utf-8",
            newline="\n",
        )
        started = time.perf_counter_ns()
        process = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
        compilation_wall_ns = time.perf_counter_ns() - started
        if process.returncode != 0 or not library.is_file():
            detail = (process.stderr or process.stdout).strip()
            raise TensorCpuCompilationError(
                f"compilação tensorial falhou ({process.returncode}): "
                f"{detail[:8_192]}"
            )
        manifest = {
            "protocol": TENSOR_CPU_BUILD_PROTOCOL,
            "backend": TENSOR_CPU_BACKEND,
            "graph_sha256": artifact.graph_sha256,
            "source_sha256": artifact.source_sha256,
            "gemm_workers": artifact.plan.gemm_workers,
            "gemm_provider": (
                artifact.plan.algebra_kernels[0].provider.to_dict()
                if artifact.plan.algebra_kernels
                else None
            ),
            "compiler": str(compiler),
            "compiler_version": compiler_version,
            "binary_sha256": _file_sha256(library),
            "command": [
                "$CC"
                if item == str(compiler)
                else "$CASULO_TENSOR_SOURCE"
                if item == str(source)
                else "$CASULO_TENSOR_LIBRARY"
                if item == str(library)
                else "-fopt-info-vec-optimized=$CASULO_VECTOR_REPORT"
                if item == f"-fopt-info-vec-optimized={vector_report}"
                else item
                for item in command
            ],
        }
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    try:
        vectorization = tuple(
            line.strip()
            for line in vector_report.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
            if line.strip()
        )
    except OSError:
        vectorization = ()
    return TensorCpuBuild(
        protocol=TENSOR_CPU_BUILD_PROTOCOL,
        backend=TENSOR_CPU_BACKEND,
        library=library,
        binary_sha256=_file_sha256(library),
        source_sha256=artifact.source_sha256,
        compiler=str(compiler),
        compiler_version=compiler_version,
        command=tuple(command),
        cache_hit=cache_hit,
        compilation_wall_ns=compilation_wall_ns,
        vectorization_report=vectorization,
    )


def execute_tensor_cpu(
    autograd: MetamorfoseAutogradIR,
    inputs: Mapping[str, Any],
    *,
    arena_budget_bytes: int = DEFAULT_ARENA_BUDGET_BYTES,
    workers: int | str = "auto",
    gemm_workers: int | str | None = None,
    provider: TensorCpuProviderChoice = "owned",
    allow_fallback: bool = True,
) -> TensorCpuRun:
    """Executa o caminho nativo e o submete às autoridades de correção."""

    plan = plan_tensor_cpu(
        autograd,
        arena_budget_bytes=arena_budget_bytes,
        workers=workers,
        gemm_workers=gemm_workers,
        provider=provider,
    )
    numpy_reference = NumpyTensorExecutor().execute(autograd, inputs)
    if not plan.eligible:
        if not allow_fallback:
            raise TensorCpuUnavailable(plan.reason or "plano inelegível")
        return _fallback_run(
            plan,
            numpy_reference,
            plan.reason or "plano inelegível",
        )
    try:
        artifact = generate_tensor_cpu_artifact(autograd, plan=plan)
        build = compile_tensor_cpu_artifact(artifact)
    except (NativeError, TensorCpuError, OSError) as exc:
        if not allow_fallback:
            raise
        return _fallback_run(
            plan,
            numpy_reference,
            f"{type(exc).__name__}: {exc}",
        )

    preparation_started = time.perf_counter_ns()
    try:
        prepared, observed, input_pointers, observed_pointers, arena = (
            _prepare_native_call(
                autograd,
                inputs,
                plan.arena_required_bytes or 0,
            )
        )
        library, function = _load_tensor_cpu_library(build, plan)
        preparation_wall_ns = time.perf_counter_ns() - preparation_started
        execution_started = time.perf_counter_ns()
        status_code = function(
            input_pointers,
            observed_pointers,
            arena["pointer"],
            plan.arena_required_bytes or 0,
            plan.workers,
            1,
        )
        execution_wall_ns = time.perf_counter_ns() - execution_started
    except (TensorCpuError, OSError) as exc:
        if not allow_fallback:
            raise
        return _fallback_run(
            plan,
            numpy_reference,
            f"{type(exc).__name__}: {exc}",
        )
    _ = prepared, library, arena["owner"]
    if status_code != 0:
        message = {
            1: "arena insuficiente",
            2: "ponteiro nulo",
            4: "provedor GEMM externo não vinculado",
            3: "workers inválido",
        }.get(status_code, f"status nativo desconhecido {status_code}")
        if not allow_fallback:
            raise TensorCpuError(message)
        return _fallback_run(plan, numpy_reference, message)

    native_execution = _native_execution(
        autograd,
        observed,
        numpy_reference,
        build,
    )
    raw_native_parity = compare_executions(
        numpy_reference,
        native_execution,
        autograd,
    )
    native_parity = TensorCpuParityReport(
        protocol=TENSOR_CPU_PARITY_PROTOCOL,
        status=raw_native_parity.status,
        reason=raw_native_parity.reason,
        reference_backend=numpy_reference.backend,
        reference_version=numpy_reference.backend_version,
        candidate_backend=native_execution.backend,
        candidate_version=native_execution.backend_version,
        graph_sha256=native_execution.graph_sha256,
        input_sha256=native_execution.input_sha256,
        checks=raw_native_parity.checks,
        tolerances=raw_native_parity.tolerances,
    )
    pytorch_parity = run_pytorch_parity(autograd, inputs)
    status = (
        "FAIL"
        if not native_parity.passed
        else "PASS"
        if pytorch_parity.status is ParityStatus.PASS
        else "INCONCLUSIVE"
    )
    return TensorCpuRun(
        protocol=TENSOR_CPU_RUN_PROTOCOL,
        status=status,
        used_native=True,
        fallback_reason=None,
        plan=plan,
        build=build,
        execution=native_execution,
        native_vs_numpy=native_parity,
        numpy_vs_pytorch=pytorch_parity,
        preparation_wall_ns=preparation_wall_ns,
        execution_wall_ns=execution_wall_ns,
    )


def prepare_tensor_cpu_executor(
    autograd: MetamorfoseAutogradIR,
    inputs: Mapping[str, Any],
    *,
    arena_budget_bytes: int = DEFAULT_ARENA_BUDGET_BYTES,
    workers: int | str = "auto",
    gemm_workers: int | str | None = None,
    provider: TensorCpuProviderChoice = "owned",
) -> PreparedTensorCpuExecutor:
    """Compila e prepara uma instância reutilizável para medição controlada."""

    plan = plan_tensor_cpu(
        autograd,
        arena_budget_bytes=arena_budget_bytes,
        workers=workers,
        gemm_workers=gemm_workers,
        provider=provider,
    )
    if not plan.eligible:
        raise TensorCpuUnavailable(plan.reason or "plano inelegível")
    artifact = generate_tensor_cpu_artifact(autograd, plan=plan)
    build = compile_tensor_cpu_artifact(artifact)
    prepared, observed, input_pointers, observed_pointers, arena = (
        _prepare_native_call(
            autograd,
            inputs,
            plan.arena_required_bytes or 0,
        )
    )
    library, function = _load_tensor_cpu_library(build, plan)
    return PreparedTensorCpuExecutor(
        autograd=autograd,
        plan=plan,
        build=build,
        input_arrays=prepared,
        observed=observed,
        input_pointers=input_pointers,
        observed_pointers=observed_pointers,
        arena=arena,
        library=library,
        function=function,
    )


def execute_tensor_cpu_file(
    graph_path: str | Path,
    input_path: str | Path,
    *,
    wrt: Iterable[str],
    loss: str | None = None,
    arena_budget_bytes: int = DEFAULT_ARENA_BUDGET_BYTES,
    workers: int | str = "auto",
    gemm_workers: int | str | None = None,
    provider: TensorCpuProviderChoice = "owned",
    allow_fallback: bool = True,
) -> TensorCpuRun:
    source = Path(input_path).expanduser().resolve()
    try:
        inputs = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TensorCpuError(f"entrada tensorial inválida: {source}: {exc}") from exc
    if not isinstance(inputs, dict):
        raise TensorCpuError("entrada tensorial precisa ser um objeto")
    autograd = compile_autograd_file(
        graph_path,
        wrt=tuple(wrt),
        loss=loss,
    )
    return execute_tensor_cpu(
        autograd,
        inputs,
        arena_budget_bytes=arena_budget_bytes,
        workers=workers,
        gemm_workers=gemm_workers,
        provider=provider,
        allow_fallback=allow_fallback,
    )


def _prepare_native_call(
    autograd: MetamorfoseAutogradIR,
    inputs: Mapping[str, Any],
    arena_required_bytes: int,
) -> tuple[Any, list[Any], Any, Any, dict[str, Any]]:
    try:
        import numpy as np
    except ImportError as exc:
        raise TensorCpuUnavailable(
            "NumPy é necessário para a fronteira tensorial"
        ) from exc
    prepared = _prepare_numeric_inputs(autograd.forward, inputs, np)
    input_arrays = [
        np.ascontiguousarray(prepared[item.name])
        for item in autograd.forward.inputs
    ]
    observations: list[Any] = []
    for instruction in autograd.forward.instructions:
        observations.append(
            np.empty(
                _static_shape(instruction.output_type),
                dtype=_numpy_dtype(instruction.output_type.dtype, np),
                order="C",
            )
        )
    for binding in autograd.gradients:
        observations.append(
            np.empty(
                _static_shape(binding.type),
                dtype=_numpy_dtype(binding.type.dtype, np),
                order="C",
            )
        )
    input_pointer_type = ctypes.c_void_p * len(input_arrays)
    observed_pointer_type = ctypes.c_void_p * len(observations)
    input_pointers = input_pointer_type(
        *(ctypes.c_void_p(item.ctypes.data) for item in input_arrays)
    )
    observed_pointers = observed_pointer_type(
        *(ctypes.c_void_p(item.ctypes.data) for item in observations)
    )
    raw_arena = ctypes.create_string_buffer(
        max(1, arena_required_bytes) + TENSOR_CPU_ALIGNMENT
    )
    raw_address = ctypes.addressof(raw_arena)
    aligned_address = _align(raw_address, TENSOR_CPU_ALIGNMENT)
    return (
        input_arrays,
        observations,
        input_pointers,
        observed_pointers,
        {
            "owner": raw_arena,
            "pointer": ctypes.c_void_p(aligned_address),
        },
    )


def _load_tensor_cpu_library(
    build: TensorCpuBuild,
    plan: TensorCpuPlan,
) -> tuple[Any, Any]:
    dll_directory = None
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        dll_directory = os.add_dll_directory(
            str(Path(build.compiler).parent)
        )
    try:
        library = ctypes.CDLL(str(build.library))
    except OSError as exc:
        raise TensorCpuUnavailable(
            f"biblioteca tensorial não carregou: {exc}"
        ) from exc
    if dll_directory is not None:
        library._casulo_dll_directory = dll_directory
    for symbol, expected in (
        ("casulo_tensor_cpu_abi", TENSOR_CPU_ABI_PROTOCOL),
        ("casulo_tensor_cpu_backend", TENSOR_CPU_BACKEND),
        ("casulo_tensor_graph_sha256", plan.graph_sha256),
    ):
        function = getattr(library, symbol)
        function.restype = ctypes.c_char_p
        actual = function().decode("ascii")
        if actual != expected:
            raise TensorCpuUnavailable(
                f"{symbol} incompatível: {actual!r} != {expected!r}"
            )
    provider = (
        plan.algebra_kernels[0].provider
        if plan.algebra_kernels
        else CASULO_OWNED_GEMM_PROVIDER
    )
    for symbol, expected in (
        ("casulo_gemm_provider_id", provider.provider_id),
        (
            "casulo_gemm_provider_binary_sha256",
            provider.binary_sha256 or "",
        ),
    ):
        function = getattr(library, symbol)
        function.restype = ctypes.c_char_p
        actual = function().decode("ascii")
        if actual != expected:
            raise TensorCpuUnavailable(
                f"{symbol} incompatível: {actual!r} != {expected!r}"
            )
    if provider.external:
        _bind_external_gemm_provider(
            library,
            provider,
            plan.gemm_workers,
        )
    execute = library.casulo_tensor_execute
    execute.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.c_int,
    ]
    execute.restype = ctypes.c_int
    return library, execute


def _bind_external_gemm_provider(
    library: Any,
    provider: GemmProviderDescriptor,
    workers: int,
) -> None:
    try:
        provider_path = resolve_provider_library(provider)
    except CasuloLinearAlgebraError as exc:
        raise TensorCpuUnavailable(str(exc)) from exc
    if provider_path is None:
        raise TensorCpuUnavailable("provedor externo sem biblioteca")
    provider_directory = None
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        provider_directory = os.add_dll_directory(
            str(provider_path.parent)
        )
    try:
        provider_library = ctypes.CDLL(str(provider_path))
        float32_kernel = getattr(
            provider_library,
            str(provider.float32_symbol),
        )
        float64_kernel = getattr(
            provider_library,
            str(provider.float64_symbol),
        )
        set_threads = getattr(
            provider_library,
            str(provider.set_threads_symbol),
        )
    except (OSError, AttributeError) as exc:
        if provider_directory is not None:
            provider_directory.close()
        raise TensorCpuUnavailable(
            f"binding do provedor GEMM falhou: {exc}"
        ) from exc
    set_threads.argtypes = [ctypes.c_int]
    set_threads.restype = None
    set_threads(workers)
    bind = library.casulo_tensor_bind_gemm_provider
    bind.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    bind.restype = ctypes.c_int
    status = bind(
        ctypes.cast(float32_kernel, ctypes.c_void_p),
        ctypes.cast(float64_kernel, ctypes.c_void_p),
        ctypes.cast(set_threads, ctypes.c_void_p),
    )
    if status != 0:
        raise TensorCpuUnavailable(
            f"provedor GEMM recusado pelo backend: status {status}"
        )
    library._casulo_provider_library = provider_library
    if provider_directory is not None:
        library._casulo_provider_directory = provider_directory


def _native_execution(
    autograd: MetamorfoseAutogradIR,
    observed: Sequence[Any],
    reference: TensorExecution,
    build: TensorCpuBuild,
) -> TensorExecution:
    forward_count = len(autograd.forward.instructions)
    forward_values = {
        instruction.result: observed[index].copy()
        for index, instruction in enumerate(autograd.forward.instructions)
    }
    outputs = {
        name: forward_values[name].copy()
        for name in autograd.forward.outputs
    }
    gradients = {
        binding.target: observed[forward_count + index].copy()
        for index, binding in enumerate(autograd.gradients)
    }
    return TensorExecution(
        protocol=TENSOR_CPU_RUN_PROTOCOL,
        backend=TENSOR_CPU_BACKEND,
        backend_version=(
            f"{TENSOR_CPU_BACKEND}+{build.binary_sha256[:16]}"
        ),
        graph_sha256=reference.graph_sha256,
        input_sha256=reference.input_sha256,
        forward_values=forward_values,
        outputs=outputs,
        gradients=gradients,
    )


def _fallback_run(
    plan: TensorCpuPlan,
    reference: TensorExecution,
    reason: str,
) -> TensorCpuRun:
    return TensorCpuRun(
        protocol=TENSOR_CPU_RUN_PROTOCOL,
        status="FALLBACK",
        used_native=False,
        fallback_reason=reason,
        plan=plan,
        build=None,
        execution=reference,
        native_vs_numpy=None,
        numpy_vs_pytorch=None,
        preparation_wall_ns=0,
        execution_wall_ns=0,
    )


def _ordered_value_names(
    autograd: MetamorfoseAutogradIR,
) -> tuple[str, ...]:
    return (
        *(item.name for item in autograd.forward.inputs),
        *(item.result for item in autograd.forward.instructions),
        *(item.result for item in autograd.backward),
    )


def _static_shape(tensor: LarvaTensor) -> tuple[int, ...]:
    if tensor.numel is None:
        raise TensorCpuUnavailable(
            "dynamic_shape_requires_reference_executor"
        )
    return tuple(int(item) for item in tensor.shape)


def _contiguous_strides(shape: Sequence[int]) -> tuple[int, ...]:
    stride = 1
    values: list[int] = []
    for dimension in reversed(shape):
        values.append(stride)
        stride *= dimension
    return tuple(reversed(values))


def _transpose_axes(
    rank: int,
    attributes: Mapping[str, Any],
) -> tuple[int, int]:
    axis0 = _normalize_axis(int(attributes.get("axis0", -2)), rank)
    axis1 = _normalize_axis(int(attributes.get("axis1", -1)), rank)
    if axis0 == axis1:
        raise TensorCpuUnavailable("transpose_axes_must_differ")
    return axis0, axis1


def _normalize_axis(axis: int, rank: int) -> int:
    normalized = axis + rank if axis < 0 else axis
    if not 0 <= normalized < rank:
        raise TensorCpuUnavailable(
            f"axis_out_of_range: {axis} for rank {rank}"
        )
    return normalized


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _c_name(value: str) -> str:
    normalized = _C_IDENTIFIER.sub("_", value)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{normalized}_{digest}"


def _c_type(dtype: TensorDType) -> str:
    if dtype is TensorDType.FLOAT32:
        return "float"
    if dtype is TensorDType.FLOAT64:
        return "double"
    raise TensorCpuUnavailable(f"dtype C não suportado: {dtype.value}")


def _numpy_dtype(dtype: TensorDType, np: Any) -> Any:
    if dtype is TensorDType.FLOAT32:
        return np.float32
    if dtype is TensorDType.FLOAT64:
        return np.float64
    raise TensorCpuUnavailable(f"dtype NumPy não suportado: {dtype.value}")


def _graph_sha256(autograd: MetamorfoseAutogradIR) -> str:
    payload = json.dumps(
        autograd.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
