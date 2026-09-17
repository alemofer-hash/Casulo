from __future__ import annotations

import json
import math
import re
import tomllib
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


TENSOR_TYPE_PROTOCOL = "casulo-tensor-type/0.1"
TENSOR_OPERATOR_ABI = "casulo-tensor-operator-abi/0.1"
TENSOR_EXTENSION_FORMAT = "casulo-tensor-extension/0.1"
TENSOR_IR_PROTOCOL = "casulo-tensor-ir/0.1"

_SYMBOLIC_DIMENSION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TensorError(ValueError):
    """Erro verificável do frontend tensorial."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class TensorDType(str, Enum):
    BOOL = "bool"
    INT32 = "int32"
    INT64 = "int64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"

    @property
    def itemsize(self) -> int:
        return {
            TensorDType.BOOL: 1,
            TensorDType.INT32: 4,
            TensorDType.INT64: 8,
            TensorDType.FLOAT32: 4,
            TensorDType.FLOAT64: 8,
        }[self]

    @property
    def is_floating(self) -> bool:
        return self in {TensorDType.FLOAT32, TensorDType.FLOAT64}


class TensorDevice(str, Enum):
    CPU = "cpu"


class TensorLayout(str, Enum):
    CONTIGUOUS = "contiguous"
    STRIDED = "strided"


class TensorOwnership(str, Enum):
    OWNED = "owned"
    BORROWED = "borrowed"
    VIEW = "view"


Dimension = int | str


@dataclass(frozen=True, slots=True)
class LarvaTensor:
    """Contrato estático de um tensor antes de qualquer alocação."""

    dtype: TensorDType
    shape: tuple[Dimension, ...]
    device: TensorDevice = TensorDevice.CPU
    layout: TensorLayout = TensorLayout.CONTIGUOUS
    ownership: TensorOwnership = TensorOwnership.OWNED
    alias_group: str | None = None
    mutable: bool = False

    def __post_init__(self) -> None:
        if not self.shape:
            raise TensorError("T5001", "tensor precisa possuir rank maior que zero")
        for dimension in self.shape:
            if isinstance(dimension, bool) or (
                isinstance(dimension, int) and dimension <= 0
            ):
                raise TensorError(
                    "T5002",
                    f"dimensão precisa ser positiva: {dimension!r}",
                )
            if isinstance(dimension, str) and not _SYMBOLIC_DIMENSION.fullmatch(
                dimension
            ):
                raise TensorError(
                    "T5003",
                    f"dimensão simbólica inválida: {dimension!r}",
                )
            if not isinstance(dimension, (int, str)):
                raise TensorError(
                    "T5003",
                    f"tipo de dimensão inválido: {type(dimension).__name__}",
                )
        if self.ownership is TensorOwnership.VIEW and not self.alias_group:
            raise TensorError(
                "T5004",
                "view precisa declarar o grupo de alias da origem",
            )
        if self.ownership is TensorOwnership.BORROWED and self.mutable:
            raise TensorError(
                "T5005",
                "entrada borrowed é imutável por contrato",
            )

    @property
    def rank(self) -> int:
        return len(self.shape)

    @property
    def numel(self) -> int | None:
        if any(isinstance(item, str) for item in self.shape):
            return None
        return math.prod(self.shape)

    @property
    def nbytes(self) -> int | None:
        elements = self.numel
        return None if elements is None else elements * self.dtype.itemsize

    def with_alias(
        self,
        alias_group: str,
        *,
        layout: TensorLayout | None = None,
    ) -> LarvaTensor:
        return replace(
            self,
            ownership=TensorOwnership.VIEW,
            alias_group=alias_group,
            layout=layout or self.layout,
            mutable=False,
        )

    def render(self) -> str:
        dimensions = ", ".join(str(item) for item in self.shape)
        suffix = (
            f", alias={self.alias_group}"
            if self.alias_group is not None
            else ""
        )
        return (
            f"Tensor<{self.dtype.value}[{dimensions}], "
            f"{self.device.value}, {self.layout.value}, "
            f"{self.ownership.value}{suffix}>"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": TENSOR_TYPE_PROTOCOL,
            "dtype": self.dtype.value,
            "shape": list(self.shape),
            "rank": self.rank,
            "device": self.device.value,
            "layout": self.layout.value,
            "ownership": self.ownership.value,
            "alias_group": self.alias_group,
            "mutable": self.mutable,
            "numel": self.numel,
            "nbytes": self.nbytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LarvaTensor:
        if not isinstance(value, Mapping):
            raise TensorError("T5000", "descritor tensorial precisa ser um objeto")
        raw_shape = value.get("shape")
        if not isinstance(raw_shape, (list, tuple)):
            raise TensorError("T5000", "shape precisa ser uma lista")
        try:
            return cls(
                dtype=TensorDType(str(value["dtype"])),
                shape=tuple(raw_shape),
                device=TensorDevice(str(value.get("device", "cpu"))),
                layout=TensorLayout(str(value.get("layout", "contiguous"))),
                ownership=TensorOwnership(
                    str(value.get("ownership", "owned"))
                ),
                alias_group=(
                    str(value["alias_group"])
                    if value.get("alias_group") is not None
                    else None
                ),
                mutable=bool(value.get("mutable", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, TensorError):
                raise
            raise TensorError(
                "T5000",
                f"descritor tensorial inválido: {exc}",
            ) from exc


ShapeRule = Callable[
    [tuple[LarvaTensor, ...], Mapping[str, Any]], tuple[Dimension, ...]
]


@dataclass(frozen=True, slots=True)
class TensorOperatorSchema:
    name: str
    version: str
    arity: int
    shape_rule: str
    dtype_rule: str = "same"
    device_rule: str = "same"
    differentiable: bool = True
    alias_input: int | None = None
    mutates_input: int | None = None

    def __post_init__(self) -> None:
        if not _SYMBOLIC_DIMENSION.fullmatch(self.name):
            raise TensorError(
                "T5101",
                f"nome de operador inválido: {self.name!r}",
            )
        if self.arity < 1:
            raise TensorError("T5102", "operador precisa consumir ao menos um tensor")
        for role, index in (
            ("alias_input", self.alias_input),
            ("mutates_input", self.mutates_input),
        ):
            if index is not None and not 0 <= index < self.arity:
                raise TensorError(
                    "T5103",
                    f"{role} fora da aridade de {self.name}",
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TensorOperatorRegistry:
    """Registro versionado; descreve sem executar extensões."""

    def __init__(self) -> None:
        self._operators: dict[str, TensorOperatorSchema] = {}

    def register(self, schema: TensorOperatorSchema) -> None:
        if schema.name in self._operators:
            raise TensorError(
                "T5104",
                f"operador já registrado: {schema.name}",
            )
        if schema.shape_rule not in _SHAPE_RULES:
            raise TensorError(
                "T5105",
                f"regra de shape desconhecida: {schema.shape_rule}",
            )
        if schema.dtype_rule not in {"same", "floating"}:
            raise TensorError(
                "T5106",
                f"regra de dtype desconhecida: {schema.dtype_rule}",
            )
        if schema.device_rule != "same":
            raise TensorError(
                "T5107",
                f"regra de device desconhecida: {schema.device_rule}",
            )
        self._operators[schema.name] = schema

    def resolve(self, name: str) -> TensorOperatorSchema:
        try:
            return self._operators[name]
        except KeyError as exc:
            raise TensorError("T5108", f"operador desconhecido: {name}") from exc

    def infer(
        self,
        name: str,
        inputs: tuple[LarvaTensor, ...],
        attributes: Mapping[str, Any] | None = None,
    ) -> LarvaTensor:
        schema = self.resolve(name)
        if len(inputs) != schema.arity:
            raise TensorError(
                "T5109",
                f"{name} recebeu {len(inputs)} entrada(s); esperado {schema.arity}",
            )
        if any(item.device is not inputs[0].device for item in inputs[1:]):
            raise TensorError(
                "T5110",
                f"{name} exige todas as entradas no mesmo device",
            )
        if any(item.dtype is not inputs[0].dtype for item in inputs[1:]):
            raise TensorError(
                "T5111",
                f"{name} exige dtype idêntico em todas as entradas",
            )
        if schema.dtype_rule == "floating" and not inputs[0].dtype.is_floating:
            raise TensorError(
                "T5112",
                f"{name} exige dtype de ponto flutuante",
            )
        if schema.mutates_input is not None:
            target = inputs[schema.mutates_input]
            if not target.mutable or target.ownership is not TensorOwnership.OWNED:
                raise TensorError(
                    "T5113",
                    f"{name} só pode mutar tensor owned e mutable",
                )
        output_shape = _SHAPE_RULES[schema.shape_rule](
            inputs,
            attributes or {},
        )
        output = LarvaTensor(
            dtype=inputs[0].dtype,
            shape=output_shape,
            device=inputs[0].device,
            layout=TensorLayout.CONTIGUOUS,
        )
        alias_index = (
            schema.alias_input
            if schema.alias_input is not None
            else schema.mutates_input
        )
        if alias_index is not None:
            source = inputs[alias_index]
            alias_group = source.alias_group or "<input>"
            output = output.with_alias(
                alias_group,
                layout=(
                    TensorLayout.STRIDED
                    if name == "transpose"
                    else source.layout
                ),
            )
        return output

    def to_dict(self) -> dict[str, Any]:
        return {
            "abi": TENSOR_OPERATOR_ABI,
            "operators": [
                self._operators[name].to_dict()
                for name in sorted(self._operators)
            ],
        }

    @classmethod
    def builtins(cls) -> TensorOperatorRegistry:
        registry = cls()
        for schema in _BUILTIN_SCHEMAS:
            registry.register(schema)
        return registry

    def load_extension(self, path: str | Path) -> tuple[str, str]:
        source = Path(path).expanduser().resolve()
        try:
            document = tomllib.loads(source.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise TensorError(
                "T5120",
                f"manifesto de extensão inválido: {source}: {exc}",
            ) from exc
        if document.get("format") != TENSOR_EXTENSION_FORMAT:
            raise TensorError(
                "T5121",
                f"formato de extensão incompatível: {document.get('format')!r}",
            )
        extension = document.get("extension")
        if not isinstance(extension, dict):
            raise TensorError("T5122", "seção [extension] ausente")
        if extension.get("abi") != TENSOR_OPERATOR_ABI:
            raise TensorError(
                "T5123",
                f"ABI tensorial incompatível: {extension.get('abi')!r}",
            )
        name = str(extension.get("name", "")).strip()
        version = str(extension.get("version", "")).strip()
        if not name or not version:
            raise TensorError(
                "T5124",
                "extensão precisa declarar name e version",
            )
        operators = document.get("operator", [])
        if not isinstance(operators, list) or not operators:
            raise TensorError(
                "T5125",
                "extensão precisa declarar ao menos um [[operator]]",
            )
        for raw in operators:
            if not isinstance(raw, dict):
                raise TensorError("T5126", "descritor de operador inválido")
            try:
                schema = TensorOperatorSchema(
                    name=str(raw["name"]),
                    version=str(raw.get("version", version)),
                    arity=int(raw["arity"]),
                    shape_rule=str(raw["shape_rule"]),
                    dtype_rule=str(raw.get("dtype_rule", "same")),
                    device_rule=str(raw.get("device_rule", "same")),
                    differentiable=bool(raw.get("differentiable", True)),
                    alias_input=(
                        int(raw["alias_input"])
                        if "alias_input" in raw
                        else None
                    ),
                    mutates_input=(
                        int(raw["mutates_input"])
                        if "mutates_input" in raw
                        else None
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise TensorError(
                    "T5126",
                    f"descritor de operador inválido: {exc}",
                ) from exc
            self.register(schema)
        return name, version


@dataclass(frozen=True, slots=True)
class TensorCall:
    result: str
    operator: str
    inputs: tuple[str, ...]
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TensorIRValue:
    name: str
    type: LarvaTensor
    origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.to_dict(),
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True)
class TensorIRInstruction:
    result: str
    operator: str
    operator_version: str
    inputs: tuple[str, ...]
    attributes: Mapping[str, Any]
    output_type: LarvaTensor

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "operator": self.operator,
            "operator_version": self.operator_version,
            "inputs": list(self.inputs),
            "attributes": dict(self.attributes),
            "output_type": self.output_type.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class TensorMemoryPlan:
    known: bool
    input_bytes: int | None
    allocated_bytes: int | None
    peak_live_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CrisalidaTensorIR:
    protocol: str
    operator_abi: str
    inputs: tuple[TensorIRValue, ...]
    instructions: tuple[TensorIRInstruction, ...]
    outputs: tuple[str, ...]
    memory: TensorMemoryPlan

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "operator_abi": self.operator_abi,
            "inputs": [item.to_dict() for item in self.inputs],
            "instructions": [item.to_dict() for item in self.instructions],
            "outputs": list(self.outputs),
            "memory": self.memory.to_dict(),
        }

    def render_text(self) -> str:
        lines = [self.protocol, f"operator-abi {self.operator_abi}", ""]
        for value in self.inputs:
            lines.append(f"input %{value.name}: {value.type.render()}")
        if self.inputs:
            lines.append("")
        for instruction in self.instructions:
            arguments = ", ".join(f"%{item}" for item in instruction.inputs)
            lines.append(
                f"%{instruction.result} = {instruction.operator}"
                f"@{instruction.operator_version}({arguments})"
                f" : {instruction.output_type.render()}"
            )
        lines.append("")
        lines.append("return " + ", ".join(f"%{item}" for item in self.outputs))
        peak = (
            str(self.memory.peak_live_bytes)
            if self.memory.peak_live_bytes is not None
            else "dynamic"
        )
        lines.append(f"memory peak-live-bytes={peak}")
        return "\n".join(lines) + "\n"

    def write_json(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return destination


def compile_tensor_graph(
    inputs: Mapping[str, LarvaTensor],
    calls: Iterable[TensorCall],
    outputs: Iterable[str],
    *,
    registry: TensorOperatorRegistry | None = None,
) -> CrisalidaTensorIR:
    active_registry = registry or TensorOperatorRegistry.builtins()
    values: dict[str, LarvaTensor] = {}
    input_values: list[TensorIRValue] = []
    for name, tensor_type in inputs.items():
        _validate_value_name(name)
        if name in values:
            raise TensorError("T5201", f"valor duplicado: {name}")
        alias = tensor_type.alias_group or f"input:{name}"
        normalized = replace(tensor_type, alias_group=alias)
        values[name] = normalized
        input_values.append(
            TensorIRValue(name=name, type=normalized, origin="input")
        )

    instructions: list[TensorIRInstruction] = []
    for call in calls:
        _validate_value_name(call.result)
        if call.result in values:
            raise TensorError("T5201", f"valor duplicado: {call.result}")
        missing = [name for name in call.inputs if name not in values]
        if missing:
            raise TensorError(
                "T5202",
                f"{call.operator} referencia valor desconhecido: {missing[0]}",
            )
        schema = active_registry.resolve(call.operator)
        source_types = tuple(values[name] for name in call.inputs)
        inferred = active_registry.infer(
            call.operator,
            source_types,
            call.attributes,
        )
        if inferred.ownership is TensorOwnership.VIEW:
            alias_index = (
                schema.alias_input
                if schema.alias_input is not None
                else schema.mutates_input
            )
            assert alias_index is not None
            source_name = call.inputs[alias_index]
            source_group = values[source_name].alias_group or f"value:{source_name}"
            inferred = replace(inferred, alias_group=source_group)
        else:
            inferred = replace(inferred, alias_group=f"value:{call.result}")
        values[call.result] = inferred
        instructions.append(
            TensorIRInstruction(
                result=call.result,
                operator=call.operator,
                operator_version=schema.version,
                inputs=call.inputs,
                attributes=dict(call.attributes),
                output_type=inferred,
            )
        )

    requested_outputs = tuple(outputs)
    if not requested_outputs:
        raise TensorError("T5203", "grafo precisa declarar ao menos uma saída")
    for name in requested_outputs:
        if name not in values:
            raise TensorError("T5204", f"saída desconhecida: {name}")
    memory = _plan_memory(values, tuple(inputs), tuple(instructions), requested_outputs)
    return CrisalidaTensorIR(
        protocol=TENSOR_IR_PROTOCOL,
        operator_abi=TENSOR_OPERATOR_ABI,
        inputs=tuple(input_values),
        instructions=tuple(instructions),
        outputs=requested_outputs,
        memory=memory,
    )


def compile_tensor_document(
    document: Mapping[str, Any],
    *,
    base_dir: str | Path | None = None,
) -> CrisalidaTensorIR:
    if document.get("format") != TENSOR_IR_PROTOCOL:
        raise TensorError(
            "T5210",
            f"formato tensorial incompatível: {document.get('format')!r}",
        )
    registry = TensorOperatorRegistry.builtins()
    root = Path(base_dir or ".").expanduser().resolve()
    raw_extensions = document.get("extensions", [])
    if not isinstance(raw_extensions, list):
        raise TensorError("T5217", "extensions precisa ser uma lista")
    for extension in raw_extensions:
        registry.load_extension(root / str(extension))
    raw_inputs = document.get("inputs")
    raw_calls = document.get("calls")
    raw_outputs = document.get("outputs")
    if not isinstance(raw_inputs, dict):
        raise TensorError("T5211", "inputs precisa ser um objeto")
    if not isinstance(raw_calls, list):
        raise TensorError("T5212", "calls precisa ser uma lista")
    if not isinstance(raw_outputs, list):
        raise TensorError("T5213", "outputs precisa ser uma lista")
    inputs = {
        str(name): LarvaTensor.from_dict(descriptor)
        for name, descriptor in raw_inputs.items()
    }
    calls: list[TensorCall] = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            raise TensorError("T5214", "chamada tensorial inválida")
        try:
            calls.append(
                TensorCall(
                    result=str(raw["result"]),
                    operator=str(raw["operator"]),
                    inputs=tuple(str(item) for item in raw["inputs"]),
                    attributes=dict(raw.get("attributes", {})),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TensorError(
                "T5214",
                f"chamada tensorial inválida: {exc}",
            ) from exc
    return compile_tensor_graph(
        inputs,
        calls,
        (str(item) for item in raw_outputs),
        registry=registry,
    )


def compile_tensor_file(path: str | Path) -> CrisalidaTensorIR:
    source = Path(path).expanduser().resolve()
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TensorError(
            "T5215",
            f"documento tensorial inválido: {source}: {exc}",
        ) from exc
    if not isinstance(document, dict):
        raise TensorError("T5216", "raiz do documento precisa ser um objeto")
    return compile_tensor_document(document, base_dir=source.parent)


def _validate_value_name(name: str) -> None:
    if not _SYMBOLIC_DIMENSION.fullmatch(name):
        raise TensorError("T5200", f"nome de valor inválido: {name!r}")


def _identity_shape(
    inputs: tuple[LarvaTensor, ...],
    _attributes: Mapping[str, Any],
) -> tuple[Dimension, ...]:
    return inputs[0].shape


def _broadcast_shape(
    inputs: tuple[LarvaTensor, ...],
    _attributes: Mapping[str, Any],
) -> tuple[Dimension, ...]:
    left, right = inputs
    result: list[Dimension] = []
    for left_dim, right_dim in zip(
        reversed(left.shape),
        reversed(right.shape),
    ):
        if left_dim == right_dim:
            result.append(left_dim)
        elif left_dim == 1:
            result.append(right_dim)
        elif right_dim == 1:
            result.append(left_dim)
        else:
            raise TensorError(
                "T5301",
                f"shapes não são broadcastáveis: {left.shape} e {right.shape}",
            )
    longer = (
        left.shape
        if len(left.shape) > len(right.shape)
        else right.shape
    )
    result.extend(reversed(longer[: abs(len(left.shape) - len(right.shape))]))
    return tuple(reversed(result))


def _matmul_shape(
    inputs: tuple[LarvaTensor, ...],
    _attributes: Mapping[str, Any],
) -> tuple[Dimension, ...]:
    left, right = inputs
    if left.rank < 2 or right.rank < 2:
        raise TensorError("T5302", "matmul exige tensores de rank >= 2")
    if left.shape[-1] != right.shape[-2]:
        raise TensorError(
            "T5303",
            f"dimensões internas incompatíveis: {left.shape[-1]} e "
            f"{right.shape[-2]}",
        )
    batch = _broadcast_shape(
        (
            replace(left, shape=left.shape[:-2] or (1,)),
            replace(right, shape=right.shape[:-2] or (1,)),
        ),
        {},
    )
    if batch == (1,) and left.rank == 2 and right.rank == 2:
        batch = ()
    return (*batch, left.shape[-2], right.shape[-1])


def _reduction_shape(
    inputs: tuple[LarvaTensor, ...],
    attributes: Mapping[str, Any],
) -> tuple[Dimension, ...]:
    shape = inputs[0].shape
    axis = attributes.get("axis")
    keepdim = bool(attributes.get("keepdim", False))
    if axis is None:
        return tuple(1 for _ in shape) if keepdim else (1,)
    if isinstance(axis, bool) or not isinstance(axis, int):
        raise TensorError("T5304", "axis precisa ser inteiro")
    normalized = axis if axis >= 0 else len(shape) + axis
    if not 0 <= normalized < len(shape):
        raise TensorError("T5305", f"axis fora do rank: {axis}")
    if keepdim:
        return tuple(1 if index == normalized else item for index, item in enumerate(shape))
    reduced = tuple(item for index, item in enumerate(shape) if index != normalized)
    return reduced or (1,)


def _reshape_shape(
    inputs: tuple[LarvaTensor, ...],
    attributes: Mapping[str, Any],
) -> tuple[Dimension, ...]:
    raw_shape = attributes.get("shape")
    if not isinstance(raw_shape, (list, tuple)) or not raw_shape:
        raise TensorError("T5306", "reshape exige atributo shape não vazio")
    target = tuple(raw_shape)
    candidate = LarvaTensor(dtype=inputs[0].dtype, shape=target)
    if (
        inputs[0].numel is not None
        and candidate.numel is not None
        and inputs[0].numel != candidate.numel
    ):
        raise TensorError(
            "T5307",
            f"reshape altera número de elementos: {inputs[0].shape} -> {target}",
        )
    return target


def _transpose_shape(
    inputs: tuple[LarvaTensor, ...],
    attributes: Mapping[str, Any],
) -> tuple[Dimension, ...]:
    shape = list(inputs[0].shape)
    try:
        axis0 = int(attributes.get("axis0", -2))
        axis1 = int(attributes.get("axis1", -1))
    except (TypeError, ValueError) as exc:
        raise TensorError(
            "T5308",
            "eixos de transpose precisam ser inteiros",
        ) from exc
    axis0 %= len(shape)
    axis1 %= len(shape)
    shape[axis0], shape[axis1] = shape[axis1], shape[axis0]
    return tuple(shape)


_SHAPE_RULES: dict[str, ShapeRule] = {
    "identity": _identity_shape,
    "broadcast": _broadcast_shape,
    "matmul": _matmul_shape,
    "reduction": _reduction_shape,
    "reshape": _reshape_shape,
    "transpose": _transpose_shape,
}

_BUILTIN_SCHEMAS = (
    TensorOperatorSchema("add", "0.1", 2, "broadcast"),
    TensorOperatorSchema("sub", "0.1", 2, "broadcast"),
    TensorOperatorSchema("mul", "0.1", 2, "broadcast"),
    TensorOperatorSchema("div", "0.1", 2, "broadcast", "floating"),
    TensorOperatorSchema("matmul", "0.1", 2, "matmul", "floating"),
    TensorOperatorSchema("relu", "0.1", 1, "identity", "floating"),
    TensorOperatorSchema("sigmoid", "0.1", 1, "identity", "floating"),
    TensorOperatorSchema("tanh", "0.1", 1, "identity", "floating"),
    TensorOperatorSchema("sum", "0.1", 1, "reduction"),
    TensorOperatorSchema("mean", "0.1", 1, "reduction", "floating"),
    TensorOperatorSchema(
        "reshape",
        "0.1",
        1,
        "reshape",
        alias_input=0,
    ),
    TensorOperatorSchema(
        "transpose",
        "0.1",
        1,
        "transpose",
        alias_input=0,
    ),
)


def _plan_memory(
    values: Mapping[str, LarvaTensor],
    input_names: tuple[str, ...],
    instructions: tuple[TensorIRInstruction, ...],
    outputs: tuple[str, ...],
) -> TensorMemoryPlan:
    if any(item.nbytes is None for item in values.values()):
        return TensorMemoryPlan(False, None, None, None)
    sizes = {name: item.nbytes or 0 for name, item in values.items()}
    input_bytes = sum(sizes[name] for name in input_names)
    allocated_bytes = sum(
        sizes[item.result]
        for item in instructions
        if item.output_type.ownership is TensorOwnership.OWNED
    )
    uses = {name: 0 for name in values}
    for instruction in instructions:
        for name in instruction.inputs:
            uses[name] += 1
    for name in outputs:
        uses[name] += 1
    live = input_bytes
    peak = live
    input_set = set(input_names)
    for instruction in instructions:
        if instruction.output_type.ownership is TensorOwnership.OWNED:
            live += sizes[instruction.result]
            peak = max(peak, live)
        for name in instruction.inputs:
            uses[name] -= 1
            value = values[name]
            if (
                uses[name] == 0
                and name not in input_set
                and value.ownership is TensorOwnership.OWNED
            ):
                live -= sizes[name]
    return TensorMemoryPlan(True, input_bytes, allocated_bytes, peak)
