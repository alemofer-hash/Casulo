"""Planejamento auditável da Álgebra Linear Casulo/T.

Este módulo não declara vitória sobre qualquer biblioteca externa. Ele recebe
um contrato matricial imutável, diagnostica o trânsito de memória e escolhe
uma ordem de execução que preserva a ordem de acumulação de cada elemento.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Any, Sequence


CASULO_LINEAR_ALGEBRA_PROTOCOL = "casulo-linear-algebra/0.1"
CASULO_GEMM_KERNEL_ABI = "casulo-gemm-kernel/0.1"
CASULO_GEMM_PROVIDER_ABI = "casulo-gemm-provider/0.1"


class CasuloLinearAlgebraError(ValueError):
    """Contrato matricial inválido ou não suportado."""


@dataclass(frozen=True, slots=True)
class GemmProviderDescriptor:
    """Proveniência do componente que executará a aritmética."""

    abi: str
    provider_id: str
    version: str
    implementation: str
    external: bool
    binary_name: str | None = None
    binary_sha256: str | None = None
    float32_symbol: str | None = None
    float64_symbol: str | None = None
    set_threads_symbol: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CASULO_OWNED_GEMM_PROVIDER = GemmProviderDescriptor(
    abi=CASULO_GEMM_PROVIDER_ABI,
    provider_id="casulo-owned-c99",
    version="0.2",
    implementation="generated-c99-openmp-host-vector-isa",
    external=False,
)


def discover_numpy_openblas_provider() -> GemmProviderDescriptor:
    """Descobre e sela o OpenBLAS ILP64 distribuído com o NumPy."""

    try:
        import numpy as np
    except ImportError as exc:
        raise CasuloLinearAlgebraError(
            "NumPy indisponível para descoberta do OpenBLAS"
        ) from exc
    library_root = Path(np.__file__).resolve().parent.parent / "numpy.libs"
    matches = sorted(library_root.glob("*openblas*.dll"))
    if len(matches) != 1:
        raise CasuloLinearAlgebraError(
            "esperado exatamente um DLL OpenBLAS em numpy.libs"
        )
    library = matches[0]
    blas = (
        getattr(np.__config__, "CONFIG", {})
        .get("Build Dependencies", {})
        .get("blas", {})
    )
    configuration = str(blas.get("openblas configuration", ""))
    if "USE64BITINT" not in configuration:
        raise CasuloLinearAlgebraError(
            "OpenBLAS do NumPy não declara ABI ILP64"
        )
    version = str(blas.get("version") or "unknown")
    return GemmProviderDescriptor(
        abi=CASULO_GEMM_PROVIDER_ABI,
        provider_id="numpy-scipy-openblas-ilp64",
        version=version,
        implementation="external-cblas-ilp64-runtime-function-pointer",
        external=True,
        binary_name=library.name,
        binary_sha256=_file_sha256(library),
        float32_symbol="scipy_cblas_sgemm64_",
        float64_symbol="scipy_cblas_dgemm64_",
        set_threads_symbol="scipy_openblas_set_num_threads64_",
    )


def resolve_provider_library(provider: GemmProviderDescriptor) -> Path | None:
    """Resolve um provedor externo somente quando nome e hash coincidem."""

    if not provider.external:
        return None
    if provider.provider_id != "numpy-scipy-openblas-ilp64":
        raise CasuloLinearAlgebraError(
            f"provedor externo sem resolver: {provider.provider_id}"
        )
    discovered = discover_numpy_openblas_provider()
    if discovered != provider:
        raise CasuloLinearAlgebraError(
            "provedor OpenBLAS instalado diverge do plano selado"
        )
    import numpy as np

    library = (
        Path(np.__file__).resolve().parent.parent
        / "numpy.libs"
        / str(provider.binary_name)
    )
    if _file_sha256(library) != provider.binary_sha256:
        raise CasuloLinearAlgebraError(
            "hash do provedor OpenBLAS diverge do plano"
        )
    return library


@dataclass(frozen=True, slots=True)
class EggGemmContract:
    """Estado bruto e imutável de C = A @ B."""

    operation: str
    dtype: str
    left_shape: tuple[int, int]
    right_shape: tuple[int, int]
    output_shape: tuple[int, int]
    left_strides: tuple[int, int]
    right_strides: tuple[int, int]
    output_strides: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        document = asdict(self)
        for key in (
            "left_shape",
            "right_shape",
            "output_shape",
            "left_strides",
            "right_strides",
            "output_strides",
        ):
            document[key] = list(document[key])
        return document


@dataclass(frozen=True, slots=True)
class LarvaTrafficProfile:
    """Diagnóstico do custo lógico e do caminho de memória."""

    multiply_adds: int
    scalar_flops: int
    logical_input_bytes: int
    logical_output_bytes: int
    arithmetic_intensity_flops_per_byte: float
    left_inner_contiguous: bool
    right_inner_contiguous: bool
    right_columns_contiguous: bool
    output_columns_contiguous: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CrisalidaGemmPlan:
    """Decisão formada antes da emissão do kernel."""

    protocol: str
    kernel_abi: str
    identity: str
    provider: GemmProviderDescriptor
    contract: EggGemmContract
    traffic: LarvaTrafficProfile
    loop_order: str
    parallel_axis: str
    vector_axis: str | None
    materializes_left: bool
    materializes_right: bool
    contracts_multiply_add: bool
    reassociates_reduction: bool
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "kernel_abi": self.kernel_abi,
            "identity": self.identity,
            "provider": self.provider.to_dict(),
            "contract": self.contract.to_dict(),
            "traffic": self.traffic.to_dict(),
            "loop_order": self.loop_order,
            "parallel_axis": self.parallel_axis,
            "vector_axis": self.vector_axis,
            "materializes_left": self.materializes_left,
            "materializes_right": self.materializes_right,
            "contracts_multiply_add": self.contracts_multiply_add,
            "reassociates_reduction": self.reassociates_reduction,
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True, slots=True)
class BorboletaAlgebraAudit:
    """Manifestação verificável da decisão, sem métrica de desempenho."""

    protocol: str
    plan_identity: str
    preserves_shape: bool
    preserves_dtype: bool
    preserves_inner_accumulation_order: bool
    provider_id: str
    external_compute_provider: bool
    claim: None = None

    @property
    def passed(self) -> bool:
        return (
            self.preserves_shape
            and self.preserves_dtype
            and self.preserves_inner_accumulation_order
            and bool(self.provider_id)
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


def form_gemm_plan(
    *,
    dtype: str,
    left_shape: Sequence[int],
    right_shape: Sequence[int],
    left_strides: Sequence[int],
    right_strides: Sequence[int],
    output_strides: Sequence[int] | None = None,
    provider: GemmProviderDescriptor = CASULO_OWNED_GEMM_PROVIDER,
) -> CrisalidaGemmPlan:
    """Forma uma escolha determinística entre dois microkernels conservadores."""

    left = _pair(left_shape, "left_shape")
    right = _pair(right_shape, "right_shape")
    left_step = _pair(left_strides, "left_strides")
    right_step = _pair(right_strides, "right_strides")
    if left[1] != right[0]:
        raise CasuloLinearAlgebraError(
            f"dimensão interna incompatível: {left[1]} != {right[0]}"
        )
    if dtype not in {"float32", "float64"}:
        raise CasuloLinearAlgebraError(f"dtype não suportado: {dtype}")
    output = (left[0], right[1])
    output_step = (
        _pair(output_strides, "output_strides")
        if output_strides is not None
        else (output[1], 1)
    )
    contract = EggGemmContract(
        operation="matmul-rank2",
        dtype=dtype,
        left_shape=left,
        right_shape=right,
        output_shape=output,
        left_strides=left_step,
        right_strides=right_step,
        output_strides=output_step,
    )
    element_bytes = 4 if dtype == "float32" else 8
    multiply_adds = math.prod(output) * left[1]
    logical_input_bytes = (math.prod(left) + math.prod(right)) * element_bytes
    logical_output_bytes = math.prod(output) * element_bytes
    traffic = LarvaTrafficProfile(
        multiply_adds=multiply_adds,
        scalar_flops=2 * multiply_adds,
        logical_input_bytes=logical_input_bytes,
        logical_output_bytes=logical_output_bytes,
        arithmetic_intensity_flops_per_byte=(
            (2 * multiply_adds)
            / (logical_input_bytes + logical_output_bytes)
        ),
        left_inner_contiguous=left_step[1] == 1,
        right_inner_contiguous=right_step[0] == 1,
        right_columns_contiguous=right_step[1] == 1,
        output_columns_contiguous=output_step[1] == 1,
    )
    if traffic.right_columns_contiguous and traffic.output_columns_contiguous:
        loop_order = "row-inner-column"
        parallel_axis = "row"
        vector_axis = "column"
        rationale = (
            "reutiliza um escalar da matriz esquerda por linha do resultado",
            "percorre matriz direita e saída contiguamente",
            "mantém a acumulação de cada saída em ordem crescente do eixo interno",
        )
    else:
        loop_order = "row-column-inner"
        parallel_axis = "row"
        vector_axis = None
        rationale = (
            "produto interno percorre os dois operandos com o melhor stride disponível",
            "evita materializar a matriz direita transposta",
            "mantém a acumulação de cada saída em ordem crescente do eixo interno",
        )
    body = {
        "protocol": CASULO_LINEAR_ALGEBRA_PROTOCOL,
        "kernel_abi": CASULO_GEMM_KERNEL_ABI,
        "provider": provider.to_dict(),
        "contract": contract.to_dict(),
        "traffic": traffic.to_dict(),
        "loop_order": loop_order,
        "parallel_axis": parallel_axis,
        "vector_axis": vector_axis,
        "materializes_left": False,
        "materializes_right": False,
        "contracts_multiply_add": True,
        "reassociates_reduction": False,
        "rationale": list(rationale),
    }
    identity = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return CrisalidaGemmPlan(
        protocol=CASULO_LINEAR_ALGEBRA_PROTOCOL,
        kernel_abi=CASULO_GEMM_KERNEL_ABI,
        identity=f"sha256:{identity}",
        provider=provider,
        contract=contract,
        traffic=traffic,
        loop_order=loop_order,
        parallel_axis=parallel_axis,
        vector_axis=vector_axis,
        materializes_left=False,
        materializes_right=False,
        contracts_multiply_add=True,
        reassociates_reduction=False,
        rationale=rationale,
    )


def audit_gemm_plan(plan: CrisalidaGemmPlan) -> BorboletaAlgebraAudit:
    """Julga apenas invariantes estruturais; nunca julga velocidade."""

    contract = plan.contract
    return BorboletaAlgebraAudit(
        protocol="casulo-linear-algebra-audit/0.1",
        plan_identity=plan.identity,
        preserves_shape=(
            contract.output_shape
            == (contract.left_shape[0], contract.right_shape[1])
            and contract.left_shape[1] == contract.right_shape[0]
        ),
        preserves_dtype=contract.dtype in {"float32", "float64"},
        preserves_inner_accumulation_order=not plan.reassociates_reduction,
        provider_id=plan.provider.provider_id,
        external_compute_provider=plan.provider.external,
    )


def _pair(values: Sequence[int], name: str) -> tuple[int, int]:
    result = tuple(int(item) for item in values)
    if len(result) != 2 or any(item <= 0 for item in result):
        raise CasuloLinearAlgebraError(
            f"{name} precisa conter duas dimensões positivas"
        )
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
