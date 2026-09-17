from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .autograd import (
    AutogradError,
    MetamorfoseAutogradIR,
    _execute_backward,
    _execute_forward,
    _prepare_numeric_inputs,
    compile_autograd_file,
)
from .tensor import LarvaTensor, TensorDType


NUMPY_EXECUTOR_PROTOCOL = "casulo-numpy-executor/0.1"
PYTORCH_ADAPTER_PROTOCOL = "casulo-pytorch-adapter/0.1"
PYTORCH_PARITY_PROTOCOL = "casulo-pytorch-parity/0.1"

_AUTO_TORCH = object()


class ParityError(AutogradError):
    """Falha de contrato do executor ou do comparador de paridade."""


class ParityStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class DTypeTolerance:
    dtype: TensorDType
    absolute: float
    relative: float

    def __post_init__(self) -> None:
        if (
            not self.dtype.is_floating
            or self.absolute < 0
            or self.relative < 0
        ):
            raise ParityError(
                "T7000",
                "tolerância exige dtype flutuante e limites não negativos",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dtype": self.dtype.value,
            "absolute": self.absolute,
            "relative": self.relative,
        }


DEFAULT_TOLERANCES = {
    TensorDType.FLOAT32: DTypeTolerance(
        TensorDType.FLOAT32,
        absolute=1e-5,
        relative=1e-4,
    ),
    TensorDType.FLOAT64: DTypeTolerance(
        TensorDType.FLOAT64,
        absolute=1e-10,
        relative=1e-9,
    ),
}


@dataclass(frozen=True, slots=True)
class ArrayDescriptor:
    dtype: str
    shape: tuple[int, ...]
    c_contiguous: bool
    finite: bool
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dtype": self.dtype,
            "shape": list(self.shape),
            "c_contiguous": self.c_contiguous,
            "finite": self.finite,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class TensorExecution:
    protocol: str
    backend: str
    backend_version: str
    graph_sha256: str
    input_sha256: str
    forward_values: Mapping[str, Any]
    outputs: Mapping[str, Any]
    gradients: Mapping[str, Any]

    def to_dict(self, *, include_values: bool = False) -> dict[str, Any]:
        document: dict[str, Any] = {
            "protocol": self.protocol,
            "backend": self.backend,
            "backend_version": self.backend_version,
            "graph_sha256": self.graph_sha256,
            "input_sha256": self.input_sha256,
            "forward_values": {
                name: _describe_array(value).to_dict()
                for name, value in self.forward_values.items()
            },
            "outputs": {
                name: _describe_array(value).to_dict()
                for name, value in self.outputs.items()
            },
            "gradients": {
                name: _describe_array(value).to_dict()
                for name, value in self.gradients.items()
            },
        }
        if include_values:
            document["output_values"] = {
                name: value.tolist()
                for name, value in self.outputs.items()
            }
            document["gradient_values"] = {
                name: value.tolist()
                for name, value in self.gradients.items()
            }
        return document


class NumpyTensorExecutor:
    protocol = NUMPY_EXECUTOR_PROTOCOL

    def execute(
        self,
        autograd: MetamorfoseAutogradIR,
        inputs: Mapping[str, Any],
    ) -> TensorExecution:
        try:
            import numpy as np
        except ImportError as exc:
            raise ParityError(
                "T7001",
                "NumPy é necessário para o executor de referência",
            ) from exc
        prepared = _prepare_numeric_inputs(autograd.forward, inputs, np)
        forward_values = _execute_forward(autograd.forward, prepared, np)
        backward_values = _execute_backward(
            autograd,
            forward_values,
            np,
        )
        intermediates = {
            item.result: np.array(
                forward_values[item.result],
                copy=True,
            )
            for item in autograd.forward.instructions
        }
        outputs = {
            name: np.array(forward_values[name], copy=True)
            for name in autograd.forward.outputs
        }
        gradients = {
            item.target: np.array(
                backward_values[item.value],
                copy=True,
            )
            for item in autograd.gradients
        }
        return TensorExecution(
            protocol=self.protocol,
            backend="numpy-reference",
            backend_version=np.__version__,
            graph_sha256=_graph_sha256(autograd),
            input_sha256=_arrays_sha256(prepared),
            forward_values=intermediates,
            outputs=outputs,
            gradients=gradients,
        )


class PyTorchTensorAdapter:
    protocol = PYTORCH_ADAPTER_PROTOCOL

    def __init__(self, torch_module: Any) -> None:
        self.torch = torch_module

    def execute(
        self,
        autograd: MetamorfoseAutogradIR,
        inputs: Mapping[str, Any],
    ) -> TensorExecution:
        try:
            import numpy as np
        except ImportError as exc:
            raise ParityError(
                "T7001",
                "NumPy é necessário para materializar a comparação",
            ) from exc
        torch = self.torch
        prepared = _prepare_numeric_inputs(autograd.forward, inputs, np)
        input_types = {
            item.name: item.type
            for item in autograd.forward.inputs
        }
        tensors: dict[str, Any] = {}
        for name, value in prepared.items():
            dtype = {
                TensorDType.FLOAT32: torch.float32,
                TensorDType.FLOAT64: torch.float64,
                TensorDType.INT32: torch.int32,
                TensorDType.INT64: torch.int64,
                TensorDType.BOOL: torch.bool,
            }[input_types[name].dtype]
            tensors[name] = torch.tensor(
                value,
                dtype=dtype,
                device="cpu",
                requires_grad=input_types[name].dtype.is_floating,
            )

        for instruction in autograd.forward.instructions:
            arguments = [
                tensors[name]
                for name in instruction.inputs
            ]
            attributes = instruction.attributes
            operator = instruction.operator
            if operator == "add":
                result = arguments[0] + arguments[1]
            elif operator == "sub":
                result = arguments[0] - arguments[1]
            elif operator == "mul":
                result = arguments[0] * arguments[1]
            elif operator == "div":
                result = arguments[0] / arguments[1]
            elif operator == "matmul":
                result = torch.matmul(arguments[0], arguments[1])
            elif operator == "relu":
                result = torch.relu(arguments[0])
            elif operator == "sigmoid":
                result = torch.sigmoid(arguments[0])
            elif operator == "tanh":
                result = torch.tanh(arguments[0])
            elif operator in {"sum", "mean"}:
                reducer = torch.sum if operator == "sum" else torch.mean
                axis = attributes.get("axis")
                keepdim = bool(attributes.get("keepdim", False))
                if axis is None:
                    result = reducer(arguments[0])
                else:
                    result = reducer(
                        arguments[0],
                        dim=int(axis),
                        keepdim=keepdim,
                    )
                if result.ndim == 0:
                    result = result.reshape(1)
            elif operator == "reshape":
                result = torch.reshape(
                    arguments[0],
                    tuple(attributes["shape"]),
                )
            elif operator == "transpose":
                result = torch.swapaxes(
                    arguments[0],
                    int(attributes.get("axis0", -2)),
                    int(attributes.get("axis1", -1)),
                )
            else:
                raise ParityError(
                    "T7002",
                    f"adaptador PyTorch não suporta: {operator}",
                )
            _assert_torch_shape(
                instruction.result,
                result,
                instruction.output_type,
            )
            tensors[instruction.result] = result

        loss = tensors[autograd.loss]
        if loss.numel() != 1:
            raise ParityError(
                "T7003",
                "loss PyTorch deixou de possuir um elemento",
            )
        loss.reshape(()).backward()
        intermediates = {
            item.result: _torch_to_numpy(tensors[item.result])
            for item in autograd.forward.instructions
        }
        outputs = {
            name: _torch_to_numpy(tensors[name])
            for name in autograd.forward.outputs
        }
        gradients: dict[str, Any] = {}
        for name in autograd.wrt:
            gradient = tensors[name].grad
            gradients[name] = (
                np.zeros_like(prepared[name])
                if gradient is None
                else _torch_to_numpy(gradient)
            )
        return TensorExecution(
            protocol=self.protocol,
            backend="pytorch-autograd-cpu",
            backend_version=str(torch.__version__),
            graph_sha256=_graph_sha256(autograd),
            input_sha256=_arrays_sha256(prepared),
            forward_values=intermediates,
            outputs=outputs,
            gradients=gradients,
        )


@dataclass(frozen=True, slots=True)
class ParityCheck:
    kind: str
    name: str
    dtype: str
    shape: tuple[int, ...]
    absolute_tolerance: float
    relative_tolerance: float
    max_absolute_error: float | None
    max_relative_error: float | None
    numpy_sha256: str
    pytorch_sha256: str
    passed: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        document = asdict(self)
        document["shape"] = list(self.shape)
        return document


@dataclass(frozen=True, slots=True)
class PyTorchParityReport:
    protocol: str
    status: ParityStatus
    reason: str | None
    graph_sha256: str
    input_sha256: str
    numpy_version: str
    pytorch_version: str | None
    device: str
    checks: tuple[ParityCheck, ...]
    tolerances: tuple[DTypeTolerance, ...]

    @property
    def passed(self) -> bool:
        return self.status is ParityStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "status": self.status.value,
            "passed": self.passed,
            "reason": self.reason,
            "graph_sha256": self.graph_sha256,
            "input_sha256": self.input_sha256,
            "numpy_version": self.numpy_version,
            "pytorch_version": self.pytorch_version,
            "device": self.device,
            "checks": [item.to_dict() for item in self.checks],
            "tolerances": [item.to_dict() for item in self.tolerances],
            "timing": None,
            "energy_joules": None,
        }


def compare_executions(
    numpy_execution: TensorExecution,
    pytorch_execution: TensorExecution,
    autograd: MetamorfoseAutogradIR,
    *,
    tolerances: Mapping[TensorDType, DTypeTolerance] | None = None,
) -> PyTorchParityReport:
    policy = dict(tolerances or DEFAULT_TOLERANCES)
    if (
        numpy_execution.graph_sha256
        != pytorch_execution.graph_sha256
        or numpy_execution.input_sha256
        != pytorch_execution.input_sha256
    ):
        raise ParityError(
            "T7010",
            "execuções não pertencem ao mesmo grafo e entradas",
        )
    value_types = _value_types(autograd)
    checks: list[ParityCheck] = []
    output_names = set(autograd.forward.outputs)
    for instruction in autograd.forward.instructions:
        name = instruction.result
        kind = (
            "loss"
            if name == autograd.loss
            else "output"
            if name in output_names
            else "intermediate"
        )
        checks.append(
            _compare_array(
                kind,
                name,
                numpy_execution.forward_values[name],
                pytorch_execution.forward_values[name],
                value_types[name],
                policy,
            )
        )
    for binding in autograd.gradients:
        checks.append(
            _compare_array(
                "gradient",
                binding.target,
                numpy_execution.gradients[binding.target],
                pytorch_execution.gradients[binding.target],
                binding.type,
                policy,
            )
        )
    status = (
        ParityStatus.PASS
        if all(item.passed for item in checks)
        else ParityStatus.FAIL
    )
    return PyTorchParityReport(
        protocol=PYTORCH_PARITY_PROTOCOL,
        status=status,
        reason=None if status is ParityStatus.PASS else "numeric mismatch",
        graph_sha256=numpy_execution.graph_sha256,
        input_sha256=numpy_execution.input_sha256,
        numpy_version=numpy_execution.backend_version,
        pytorch_version=pytorch_execution.backend_version,
        device="cpu",
        checks=tuple(checks),
        tolerances=tuple(policy[name] for name in sorted(policy, key=lambda item: item.value)),
    )


def run_pytorch_parity(
    autograd: MetamorfoseAutogradIR,
    inputs: Mapping[str, Any],
    *,
    tolerances: Mapping[TensorDType, DTypeTolerance] | None = None,
    torch_module: Any = _AUTO_TORCH,
) -> PyTorchParityReport:
    numpy_execution = NumpyTensorExecutor().execute(autograd, inputs)
    if torch_module is _AUTO_TORCH:
        try:
            import torch as torch_module
        except ImportError:
            torch_module = None
    if torch_module is None:
        return _inconclusive_report(
            numpy_execution,
            "PyTorch indisponível",
            tolerances,
        )
    try:
        pytorch_execution = PyTorchTensorAdapter(torch_module).execute(
            autograd,
            inputs,
        )
    except Exception as exc:
        return _inconclusive_report(
            numpy_execution,
            f"adaptador PyTorch indisponível para o grafo: "
            f"{type(exc).__name__}: {exc}",
            tolerances,
            pytorch_version=str(
                getattr(torch_module, "__version__", "unknown")
            ),
        )
    return compare_executions(
        numpy_execution,
        pytorch_execution,
        autograd,
        tolerances=tolerances,
    )


def execute_numpy_file(
    graph_path: str | Path,
    input_path: str | Path,
    *,
    wrt: tuple[str, ...],
    loss: str | None = None,
) -> TensorExecution:
    inputs = _read_input_file(input_path)
    autograd = compile_autograd_file(
        graph_path,
        wrt=wrt,
        loss=loss,
    )
    return NumpyTensorExecutor().execute(autograd, inputs)


def run_pytorch_parity_file(
    graph_path: str | Path,
    input_path: str | Path,
    *,
    wrt: tuple[str, ...],
    loss: str | None = None,
) -> PyTorchParityReport:
    inputs = _read_input_file(input_path)
    autograd = compile_autograd_file(
        graph_path,
        wrt=wrt,
        loss=loss,
    )
    return run_pytorch_parity(autograd, inputs)


def _read_input_file(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityError(
            "T7020",
            f"entrada tensorial inválida: {source}: {exc}",
        ) from exc
    if not isinstance(document, dict):
        raise ParityError(
            "T7021",
            "entrada tensorial precisa ser um objeto",
        )
    return document


def _compare_array(
    kind: str,
    name: str,
    numpy_value: Any,
    pytorch_value: Any,
    tensor_type: LarvaTensor,
    policy: Mapping[TensorDType, DTypeTolerance],
) -> ParityCheck:
    try:
        import numpy as np
    except ImportError as exc:
        raise ParityError("T7001", "NumPy é necessário") from exc
    tolerance = policy.get(tensor_type.dtype)
    if tolerance is None:
        raise ParityError(
            "T7011",
            f"tolerância ausente para {tensor_type.dtype.value}",
        )
    left = np.asarray(numpy_value)
    right = np.asarray(pytorch_value)
    left_descriptor = _describe_array(left)
    right_descriptor = _describe_array(right)
    if left.shape != right.shape:
        return ParityCheck(
            kind=kind,
            name=name,
            dtype=tensor_type.dtype.value,
            shape=tuple(left.shape),
            absolute_tolerance=tolerance.absolute,
            relative_tolerance=tolerance.relative,
            max_absolute_error=None,
            max_relative_error=None,
            numpy_sha256=left_descriptor.sha256,
            pytorch_sha256=right_descriptor.sha256,
            passed=False,
            reason=f"shape mismatch: {left.shape} != {right.shape}",
        )
    if left.dtype != right.dtype:
        return ParityCheck(
            kind=kind,
            name=name,
            dtype=tensor_type.dtype.value,
            shape=tuple(left.shape),
            absolute_tolerance=tolerance.absolute,
            relative_tolerance=tolerance.relative,
            max_absolute_error=None,
            max_relative_error=None,
            numpy_sha256=left_descriptor.sha256,
            pytorch_sha256=right_descriptor.sha256,
            passed=False,
            reason=f"dtype mismatch: {left.dtype} != {right.dtype}",
        )
    if not left_descriptor.finite or not right_descriptor.finite:
        return ParityCheck(
            kind=kind,
            name=name,
            dtype=tensor_type.dtype.value,
            shape=tuple(left.shape),
            absolute_tolerance=tolerance.absolute,
            relative_tolerance=tolerance.relative,
            max_absolute_error=None,
            max_relative_error=None,
            numpy_sha256=left_descriptor.sha256,
            pytorch_sha256=right_descriptor.sha256,
            passed=False,
            reason="non-finite value",
        )
    difference = np.abs(
        left.astype(np.float64) - right.astype(np.float64)
    )
    denominator = np.maximum(
        np.maximum(np.abs(left), np.abs(right)),
        np.finfo(np.float64).tiny,
    )
    relative = difference / denominator
    allowed = (
        tolerance.absolute
        + tolerance.relative * np.abs(left.astype(np.float64))
    )
    passed = bool(np.all(difference <= allowed))
    return ParityCheck(
        kind=kind,
        name=name,
        dtype=tensor_type.dtype.value,
        shape=tuple(left.shape),
        absolute_tolerance=tolerance.absolute,
        relative_tolerance=tolerance.relative,
        max_absolute_error=float(np.max(difference)),
        max_relative_error=float(np.max(relative)),
        numpy_sha256=left_descriptor.sha256,
        pytorch_sha256=right_descriptor.sha256,
        passed=passed,
        reason=None if passed else "numeric mismatch",
    )


def _inconclusive_report(
    numpy_execution: TensorExecution,
    reason: str,
    tolerances: Mapping[TensorDType, DTypeTolerance] | None,
    *,
    pytorch_version: str | None = None,
) -> PyTorchParityReport:
    policy = dict(tolerances or DEFAULT_TOLERANCES)
    return PyTorchParityReport(
        protocol=PYTORCH_PARITY_PROTOCOL,
        status=ParityStatus.INCONCLUSIVE,
        reason=reason,
        graph_sha256=numpy_execution.graph_sha256,
        input_sha256=numpy_execution.input_sha256,
        numpy_version=numpy_execution.backend_version,
        pytorch_version=pytorch_version,
        device="cpu",
        checks=(),
        tolerances=tuple(policy[name] for name in sorted(policy, key=lambda item: item.value)),
    )


def _value_types(
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
    return values


def _assert_torch_shape(
    name: str,
    value: Any,
    tensor_type: LarvaTensor,
) -> None:
    if value.ndim != tensor_type.rank:
        raise ParityError(
            "T7030",
            f"PyTorch produziu rank inválido para {name}: "
            f"{value.ndim} != {tensor_type.rank}",
        )
    for actual, declared in zip(value.shape, tensor_type.shape):
        if isinstance(declared, int) and actual != declared:
            raise ParityError(
                "T7031",
                f"PyTorch produziu shape inválido para {name}: "
                f"{tuple(value.shape)} != {tensor_type.shape}",
            )


def _torch_to_numpy(value: Any) -> Any:
    return value.detach().cpu().contiguous().numpy().copy()


def _graph_sha256(autograd: MetamorfoseAutogradIR) -> str:
    payload = json.dumps(
        autograd.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _arrays_sha256(values: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    for name in sorted(values):
        descriptor = _describe_array(values[name])
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(descriptor.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _describe_array(value: Any) -> ArrayDescriptor:
    try:
        import numpy as np
    except ImportError as exc:
        raise ParityError("T7001", "NumPy é necessário") from exc
    array = np.asarray(value)
    contiguous = np.ascontiguousarray(array)
    header = json.dumps(
        {
            "dtype": str(contiguous.dtype),
            "shape": list(contiguous.shape),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(header)
    digest.update(b"\0")
    digest.update(contiguous.tobytes(order="C"))
    finite = bool(np.all(np.isfinite(contiguous)))
    return ArrayDescriptor(
        dtype=str(contiguous.dtype),
        shape=tuple(int(item) for item in contiguous.shape),
        c_contiguous=bool(contiguous.flags.c_contiguous),
        finite=finite,
        sha256=digest.hexdigest(),
    )
