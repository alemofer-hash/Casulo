from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .tensor import (
    CrisalidaTensorIR,
    LarvaTensor,
    TensorDType,
    TensorError,
    TensorIRInstruction,
    TensorOwnership,
    compile_tensor_file,
)


GRADIENT_RULE_ABI = "casulo-gradient-rule-abi/0.1"
AUTOGRAD_IR_PROTOCOL = "casulo-autograd-ir/0.1"
GRADIENT_CHECK_PROTOCOL = "casulo-gradient-check/0.1"


class AutogradError(TensorError):
    """Erro verificável da formação ou validação do backward."""


@dataclass(frozen=True, slots=True)
class GradientRule:
    operator: str
    operator_version: str
    rule_version: str
    kind: str
    differentiable_inputs: tuple[int, ...]

    @property
    def identity(self) -> str:
        return (
            f"{self.operator}@{self.operator_version}/"
            f"{self.kind}@{self.rule_version}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "operator_version": self.operator_version,
            "rule_version": self.rule_version,
            "kind": self.kind,
            "differentiable_inputs": list(self.differentiable_inputs),
            "identity": self.identity,
        }


class GradientRuleRegistry:
    """Registro fechado de regras VJP, separado do executor numérico."""

    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], GradientRule] = {}

    def register(self, rule: GradientRule) -> None:
        key = (rule.operator, rule.operator_version)
        if key in self._rules:
            raise AutogradError(
                "T6001",
                f"regra de gradiente duplicada: {rule.operator}@"
                f"{rule.operator_version}",
            )
        if rule.kind not in _RULE_KINDS:
            raise AutogradError(
                "T6002",
                f"tipo de regra de gradiente desconhecido: {rule.kind}",
            )
        if (
            not rule.differentiable_inputs
            or len(set(rule.differentiable_inputs))
            != len(rule.differentiable_inputs)
            or any(index < 0 for index in rule.differentiable_inputs)
        ):
            raise AutogradError(
                "T6003",
                f"entradas diferenciáveis inválidas em {rule.identity}",
            )
        self._rules[key] = rule

    def resolve(self, operator: str, version: str) -> GradientRule:
        try:
            return self._rules[(operator, version)]
        except KeyError as exc:
            raise AutogradError(
                "T6004",
                f"regra de gradiente ausente: {operator}@{version}",
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "abi": GRADIENT_RULE_ABI,
            "rules": [
                self._rules[key].to_dict()
                for key in sorted(self._rules)
            ],
        }

    @classmethod
    def builtins(cls) -> GradientRuleRegistry:
        registry = cls()
        for rule in _BUILTIN_GRADIENT_RULES:
            registry.register(rule)
        return registry


@dataclass(frozen=True, slots=True)
class AutogradInstruction:
    result: str
    operator: str
    inputs: tuple[str, ...]
    attributes: Mapping[str, Any]
    output_type: LarvaTensor
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "operator": self.operator,
            "inputs": list(self.inputs),
            "attributes": dict(self.attributes),
            "output_type": self.output_type.to_dict(),
            "rule": self.rule,
        }


@dataclass(frozen=True, slots=True)
class GradientBinding:
    target: str
    value: str
    type: LarvaTensor

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "value": self.value,
            "type": self.type.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MetamorfoseAutogradIR:
    protocol: str
    gradient_abi: str
    loss: str
    wrt: tuple[str, ...]
    forward: CrisalidaTensorIR
    rules: tuple[GradientRule, ...]
    backward: tuple[AutogradInstruction, ...]
    gradients: tuple[GradientBinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "gradient_abi": self.gradient_abi,
            "loss": self.loss,
            "wrt": list(self.wrt),
            "forward": self.forward.to_dict(),
            "rules": [rule.to_dict() for rule in self.rules],
            "backward": [item.to_dict() for item in self.backward],
            "gradients": [item.to_dict() for item in self.gradients],
        }

    def render_text(self) -> str:
        lines = [
            self.protocol,
            f"gradient-abi {self.gradient_abi}",
            f"loss %{self.loss}",
            "wrt " + ", ".join(f"%{item}" for item in self.wrt),
            "",
            "backward {",
        ]
        for instruction in self.backward:
            arguments = ", ".join(f"%{item}" for item in instruction.inputs)
            lines.append(
                f"  %{instruction.result} = {instruction.operator}"
                f"({arguments}) : {instruction.output_type.render()}"
                f"  # {instruction.rule}"
            )
        lines.append("}")
        lines.append("")
        for binding in self.gradients:
            lines.append(f"gradient %{binding.target} = %{binding.value}")
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


class _BackwardBuilder:
    def __init__(
        self,
        values: Mapping[str, LarvaTensor],
    ) -> None:
        self.values = dict(values)
        self.instructions: list[AutogradInstruction] = []
        self._counter = 0

    def emit(
        self,
        operator: str,
        inputs: Iterable[str],
        output_type: LarvaTensor,
        *,
        rule: str,
        attributes: Mapping[str, Any] | None = None,
        label: str = "gradient",
    ) -> str:
        self._counter += 1
        result = f"g{self._counter:04d}_{label}"
        normalized = replace(
            output_type,
            ownership=TensorOwnership.OWNED,
            alias_group=f"gradient:{result}",
            mutable=False,
        )
        input_names = tuple(inputs)
        for name in input_names:
            if name not in self.values:
                raise AutogradError(
                    "T6005",
                    f"backward referencia valor desconhecido: {name}",
                )
        self.values[result] = normalized
        self.instructions.append(
            AutogradInstruction(
                result=result,
                operator=operator,
                inputs=input_names,
                attributes=dict(attributes or {}),
                output_type=normalized,
                rule=rule,
            )
        )
        return result


def compile_autograd(
    forward: CrisalidaTensorIR,
    *,
    wrt: Iterable[str],
    loss: str | None = None,
    registry: GradientRuleRegistry | None = None,
) -> MetamorfoseAutogradIR:
    active_registry = registry or GradientRuleRegistry.builtins()
    values = _forward_values(forward)
    loss_name = loss or (
        forward.outputs[0]
        if len(forward.outputs) == 1
        else None
    )
    if loss_name is None:
        raise AutogradError(
            "T6010",
            "grafo com múltiplas saídas exige loss explícita",
        )
    if loss_name not in forward.outputs or loss_name not in values:
        raise AutogradError(
            "T6011",
            f"loss precisa ser uma saída declarada: {loss_name}",
        )
    loss_type = values[loss_name]
    if not loss_type.dtype.is_floating:
        raise AutogradError("T6012", "loss precisa possuir dtype flutuante")
    if loss_type.numel != 1:
        raise AutogradError(
            "T6013",
            f"loss precisa ser escalar; shape recebido: {loss_type.shape}",
        )

    requested = tuple(wrt)
    if not requested:
        raise AutogradError("T6014", "wrt precisa declarar ao menos um tensor")
    input_names = {item.name for item in forward.inputs}
    if len(set(requested)) != len(requested):
        raise AutogradError("T6015", "wrt contém tensor duplicado")
    for name in requested:
        if name not in input_names:
            raise AutogradError(
                "T6016",
                f"wrt precisa referenciar uma entrada do grafo: {name}",
            )
        if not values[name].dtype.is_floating:
            raise AutogradError(
                "T6017",
                f"gradiente só é definido para entrada flutuante: {name}",
            )

    builder = _BackwardBuilder(values)
    contributions: dict[str, list[str]] = {name: [] for name in values}
    seed = builder.emit(
        "ones_like",
        (loss_name,),
        loss_type,
        rule="seed/0.1",
        label=f"seed_{loss_name}",
    )
    contributions[loss_name].append(seed)
    used_rules: dict[str, GradientRule] = {}

    for instruction in reversed(forward.instructions):
        result_contributions = contributions[instruction.result]
        if not result_contributions:
            continue
        output_gradient = _accumulate(
            builder,
            instruction.result,
            result_contributions,
            values[instruction.result],
        )
        rule = active_registry.resolve(
            instruction.operator,
            instruction.operator_version,
        )
        used_rules[rule.identity] = rule
        generated = _apply_rule(
            builder,
            instruction,
            output_gradient,
            rule,
            values,
        )
        for input_index, gradient_name in generated:
            if input_index >= len(instruction.inputs):
                raise AutogradError(
                    "T6018",
                    f"regra {rule.identity} excede a aridade do operador",
                )
            contributions[instruction.inputs[input_index]].append(
                gradient_name
            )

    gradients: list[GradientBinding] = []
    for name in requested:
        if contributions[name]:
            gradient_name = _accumulate(
                builder,
                name,
                contributions[name],
                values[name],
            )
        else:
            gradient_name = builder.emit(
                "zeros_like",
                (name,),
                values[name],
                rule="disconnected/0.1",
                label=f"zero_{name}",
            )
        gradients.append(
            GradientBinding(
                target=name,
                value=gradient_name,
                type=builder.values[gradient_name],
            )
        )
    pruned_backward = _prune_backward(
        builder.instructions,
        gradients,
    )

    return MetamorfoseAutogradIR(
        protocol=AUTOGRAD_IR_PROTOCOL,
        gradient_abi=GRADIENT_RULE_ABI,
        loss=loss_name,
        wrt=requested,
        forward=forward,
        rules=tuple(used_rules[name] for name in sorted(used_rules)),
        backward=pruned_backward,
        gradients=tuple(gradients),
    )


def compile_autograd_file(
    path: str | Path,
    *,
    wrt: Iterable[str],
    loss: str | None = None,
) -> MetamorfoseAutogradIR:
    return compile_autograd(
        compile_tensor_file(path),
        wrt=wrt,
        loss=loss,
    )


def _forward_values(
    forward: CrisalidaTensorIR,
) -> dict[str, LarvaTensor]:
    values = {item.name: item.type for item in forward.inputs}
    for instruction in forward.instructions:
        values[instruction.result] = instruction.output_type
    return values


def _prune_backward(
    instructions: Iterable[AutogradInstruction],
    gradients: Iterable[GradientBinding],
) -> tuple[AutogradInstruction, ...]:
    """Remove trabalho que não alcança nenhum gradiente solicitado."""

    ordered = tuple(instructions)
    backward_values = {item.result for item in ordered}
    live = {item.value for item in gradients}
    selected: list[AutogradInstruction] = []
    for instruction in reversed(ordered):
        if instruction.result not in live:
            continue
        selected.append(instruction)
        live.update(
            name
            for name in instruction.inputs
            if name in backward_values
        )
    selected.reverse()
    return tuple(selected)


def _accumulate(
    builder: _BackwardBuilder,
    target: str,
    contributions: list[str],
    target_type: LarvaTensor,
) -> str:
    result = contributions[0]
    for index, contribution in enumerate(contributions[1:], start=2):
        result = builder.emit(
            "add",
            (result, contribution),
            target_type,
            rule="accumulate/0.1",
            attributes={
                "target": target,
                "ordinal": index,
            },
            label=f"acc_{target}",
        )
    return result


def _apply_rule(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    output_gradient: str,
    rule: GradientRule,
    values: Mapping[str, LarvaTensor],
) -> tuple[tuple[int, str], ...]:
    source_types = tuple(values[name] for name in instruction.inputs)
    if any(not item.dtype.is_floating for item in source_types):
        raise AutogradError(
            "T6019",
            f"{rule.identity} recebeu entrada não flutuante",
        )
    handler = _RULE_KINDS[rule.kind]
    generated = handler(
        builder,
        instruction,
        output_gradient,
        source_types,
        rule,
    )
    allowed = set(rule.differentiable_inputs)
    if any(index not in allowed for index, _ in generated):
        raise AutogradError(
            "T6020",
            f"regra {rule.identity} gerou entrada não declarada",
        )
    return generated


def _reduce_to_input(
    builder: _BackwardBuilder,
    gradient: str,
    input_name: str,
    input_type: LarvaTensor,
    rule: GradientRule,
    index: int,
) -> str:
    return builder.emit(
        "reduce_to_shape",
        (gradient, input_name),
        input_type,
        rule=rule.identity,
        attributes={"input_index": index},
        label=f"d_{input_name}",
    )


def _rule_add(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    return tuple(
        (
            index,
            _reduce_to_input(
                builder,
                gradient,
                instruction.inputs[index],
                source_types[index],
                rule,
                index,
            ),
        )
        for index in rule.differentiable_inputs
    )


def _rule_sub(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    left = _reduce_to_input(
        builder,
        gradient,
        instruction.inputs[0],
        source_types[0],
        rule,
        0,
    )
    negated = builder.emit(
        "neg",
        (gradient,),
        builder.values[gradient],
        rule=rule.identity,
        label="neg",
    )
    right = _reduce_to_input(
        builder,
        negated,
        instruction.inputs[1],
        source_types[1],
        rule,
        1,
    )
    return ((0, left), (1, right))


def _rule_mul(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    if instruction.inputs[0] == instruction.inputs[1]:
        raw = builder.emit(
            "mul",
            (gradient, instruction.inputs[0]),
            builder.values[instruction.result],
            rule=rule.identity,
            label=f"raw_d_{instruction.inputs[0]}",
        )
        doubled = builder.emit(
            "add",
            (raw, raw),
            builder.values[instruction.result],
            rule=rule.identity,
            attributes={"algebra": "square-derivative"},
            label=f"d_{instruction.inputs[0]}",
        )
        reduced = _reduce_to_input(
            builder,
            doubled,
            instruction.inputs[0],
            source_types[0],
            rule,
            0,
        )
        return ((0, reduced),)
    result: list[tuple[int, str]] = []
    other = (1, 0)
    for index in rule.differentiable_inputs:
        raw = builder.emit(
            "mul",
            (gradient, instruction.inputs[other[index]]),
            builder.values[instruction.result],
            rule=rule.identity,
            label=f"raw_d_{instruction.inputs[index]}",
        )
        result.append(
            (
                index,
                _reduce_to_input(
                    builder,
                    raw,
                    instruction.inputs[index],
                    source_types[index],
                    rule,
                    index,
                ),
            )
        )
    return tuple(result)


def _rule_div(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    left_raw = builder.emit(
        "div",
        (gradient, instruction.inputs[1]),
        builder.values[instruction.result],
        rule=rule.identity,
        label="raw_d_left",
    )
    left = _reduce_to_input(
        builder,
        left_raw,
        instruction.inputs[0],
        source_types[0],
        rule,
        0,
    )
    numerator = builder.emit(
        "mul",
        (gradient, instruction.inputs[0]),
        builder.values[instruction.result],
        rule=rule.identity,
        label="div_numerator",
    )
    denominator = builder.emit(
        "mul",
        (instruction.inputs[1], instruction.inputs[1]),
        source_types[1],
        rule=rule.identity,
        label="div_denominator",
    )
    quotient = builder.emit(
        "div",
        (numerator, denominator),
        builder.values[instruction.result],
        rule=rule.identity,
        label="raw_d_right",
    )
    negated = builder.emit(
        "neg",
        (quotient,),
        builder.values[instruction.result],
        rule=rule.identity,
        label="neg_d_right",
    )
    right = _reduce_to_input(
        builder,
        negated,
        instruction.inputs[1],
        source_types[1],
        rule,
        1,
    )
    return ((0, left), (1, right))


def _rule_matmul(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    left_type, right_type = source_types
    if left_type.rank != 2 or right_type.rank != 2:
        raise AutogradError(
            "T6021",
            "backward de matmul 0.1 suporta somente matrizes de rank 2",
        )
    right_transpose_type = replace(
        right_type,
        shape=(right_type.shape[1], right_type.shape[0]),
    )
    right_transpose = builder.emit(
        "transpose",
        (instruction.inputs[1],),
        right_transpose_type,
        rule=rule.identity,
        attributes={"axis0": 0, "axis1": 1},
        label="transpose_right",
    )
    left_gradient = builder.emit(
        "matmul",
        (gradient, right_transpose),
        left_type,
        rule=rule.identity,
        label=f"d_{instruction.inputs[0]}",
    )
    left_transpose_type = replace(
        left_type,
        shape=(left_type.shape[1], left_type.shape[0]),
    )
    left_transpose = builder.emit(
        "transpose",
        (instruction.inputs[0],),
        left_transpose_type,
        rule=rule.identity,
        attributes={"axis0": 0, "axis1": 1},
        label="transpose_left",
    )
    right_gradient = builder.emit(
        "matmul",
        (left_transpose, gradient),
        right_type,
        rule=rule.identity,
        label=f"d_{instruction.inputs[1]}",
    )
    return ((0, left_gradient), (1, right_gradient))


def _rule_activation(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    result = builder.emit(
        f"{instruction.operator}_backward",
        (gradient, instruction.inputs[0], instruction.result),
        source_types[0],
        rule=rule.identity,
        label=f"d_{instruction.inputs[0]}",
    )
    return ((0, result),)


def _rule_reduction(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    result = builder.emit(
        f"{instruction.operator}_backward",
        (gradient, instruction.inputs[0]),
        source_types[0],
        rule=rule.identity,
        attributes=instruction.attributes,
        label=f"d_{instruction.inputs[0]}",
    )
    return ((0, result),)


def _rule_reshape(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    result = builder.emit(
        "reshape",
        (gradient,),
        source_types[0],
        rule=rule.identity,
        attributes={"shape": list(source_types[0].shape)},
        label=f"d_{instruction.inputs[0]}",
    )
    return ((0, result),)


def _rule_transpose(
    builder: _BackwardBuilder,
    instruction: TensorIRInstruction,
    gradient: str,
    source_types: tuple[LarvaTensor, ...],
    rule: GradientRule,
) -> tuple[tuple[int, str], ...]:
    result = builder.emit(
        "transpose",
        (gradient,),
        source_types[0],
        rule=rule.identity,
        attributes=instruction.attributes,
        label=f"d_{instruction.inputs[0]}",
    )
    return ((0, result),)


_RULE_KINDS = {
    "add": _rule_add,
    "sub": _rule_sub,
    "mul": _rule_mul,
    "div": _rule_div,
    "matmul-rank2": _rule_matmul,
    "activation": _rule_activation,
    "reduction": _rule_reduction,
    "reshape": _rule_reshape,
    "transpose": _rule_transpose,
}

_BUILTIN_GRADIENT_RULES = (
    GradientRule("add", "0.1", "0.1", "add", (0, 1)),
    GradientRule("sub", "0.1", "0.1", "sub", (0, 1)),
    GradientRule("mul", "0.1", "0.1", "mul", (0, 1)),
    GradientRule("div", "0.1", "0.1", "div", (0, 1)),
    GradientRule("matmul", "0.1", "0.1", "matmul-rank2", (0, 1)),
    GradientRule("relu", "0.1", "0.1", "activation", (0,)),
    GradientRule("sigmoid", "0.1", "0.1", "activation", (0,)),
    GradientRule("tanh", "0.1", "0.1", "activation", (0,)),
    GradientRule("sum", "0.1", "0.1", "reduction", (0,)),
    GradientRule("mean", "0.1", "0.1", "reduction", (0,)),
    GradientRule("reshape", "0.1", "0.1", "reshape", (0,)),
    GradientRule("transpose", "0.1", "0.1", "transpose", (0,)),
)


@dataclass(frozen=True, slots=True)
class GradientTargetCheck:
    target: str
    elements: int
    max_absolute_error: float
    max_relative_error: float
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GradientCheckReport:
    protocol: str
    autograd_protocol: str
    epsilon: float
    absolute_tolerance: float
    relative_tolerance: float
    checked_elements: int
    passed: bool
    targets: tuple[GradientTargetCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "autograd_protocol": self.autograd_protocol,
            "epsilon": self.epsilon,
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
            "checked_elements": self.checked_elements,
            "passed": self.passed,
            "targets": [item.to_dict() for item in self.targets],
        }


def check_gradients(
    autograd: MetamorfoseAutogradIR,
    inputs: Mapping[str, Any],
    *,
    epsilon: float = 1e-6,
    absolute_tolerance: float = 1e-6,
    relative_tolerance: float = 1e-5,
    max_elements: int = 4_096,
) -> GradientCheckReport:
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise AutogradError("T6101", "epsilon precisa ser positivo e finito")
    if absolute_tolerance < 0 or relative_tolerance < 0:
        raise AutogradError("T6102", "tolerâncias não podem ser negativas")
    try:
        import numpy as np
    except ImportError as exc:
        raise AutogradError(
            "T6103",
            "NumPy é necessário somente para a verificação numérica",
        ) from exc

    prepared = _prepare_numeric_inputs(autograd.forward, inputs, np)
    total = sum(prepared[name].size for name in autograd.wrt)
    if total > max_elements:
        raise AutogradError(
            "T6104",
            f"gradient check excede max_elements: {total} > {max_elements}",
        )
    forward_values = _execute_forward(autograd.forward, prepared, np)
    backward_values = _execute_backward(
        autograd,
        forward_values,
        np,
    )
    analytic = {
        item.target: np.array(
            backward_values[item.value],
            dtype=np.float64,
            copy=True,
        )
        for item in autograd.gradients
    }

    target_reports: list[GradientTargetCheck] = []
    for target in autograd.wrt:
        numerical = np.zeros_like(prepared[target], dtype=np.float64)
        working = {
            name: np.array(value, copy=True)
            for name, value in prepared.items()
        }
        for index in np.ndindex(working[target].shape):
            original = float(working[target][index])
            working[target][index] = original + epsilon
            plus = _loss_value(autograd, working, np)
            working[target][index] = original - epsilon
            minus = _loss_value(autograd, working, np)
            working[target][index] = original
            numerical[index] = (plus - minus) / (2.0 * epsilon)
        difference = np.abs(analytic[target] - numerical)
        denominator = np.maximum(
            np.maximum(np.abs(analytic[target]), np.abs(numerical)),
            np.finfo(np.float64).tiny,
        )
        relative = difference / denominator
        allowed = absolute_tolerance + relative_tolerance * np.abs(numerical)
        target_reports.append(
            GradientTargetCheck(
                target=target,
                elements=int(numerical.size),
                max_absolute_error=float(np.max(difference)),
                max_relative_error=float(np.max(relative)),
                passed=bool(np.all(difference <= allowed)),
            )
        )
    return GradientCheckReport(
        protocol=GRADIENT_CHECK_PROTOCOL,
        autograd_protocol=autograd.protocol,
        epsilon=epsilon,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        checked_elements=total,
        passed=all(item.passed for item in target_reports),
        targets=tuple(target_reports),
    )


def check_gradients_file(
    graph_path: str | Path,
    input_path: str | Path,
    *,
    wrt: Iterable[str],
    loss: str | None = None,
    epsilon: float = 1e-6,
    absolute_tolerance: float = 1e-6,
    relative_tolerance: float = 1e-5,
    max_elements: int = 4_096,
) -> GradientCheckReport:
    inputs_source = Path(input_path).expanduser().resolve()
    try:
        inputs = json.loads(inputs_source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutogradError(
            "T6105",
            f"entrada do gradient check inválida: {inputs_source}: {exc}",
        ) from exc
    if not isinstance(inputs, dict):
        raise AutogradError("T6106", "entrada numérica precisa ser um objeto")
    autograd = compile_autograd_file(graph_path, wrt=wrt, loss=loss)
    return check_gradients(
        autograd,
        inputs,
        epsilon=epsilon,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        max_elements=max_elements,
    )


def _prepare_numeric_inputs(
    forward: CrisalidaTensorIR,
    inputs: Mapping[str, Any],
    np: Any,
) -> dict[str, Any]:
    expected = {item.name: item.type for item in forward.inputs}
    if set(inputs) != set(expected):
        missing = sorted(set(expected) - set(inputs))
        extra = sorted(set(inputs) - set(expected))
        raise AutogradError(
            "T6110",
            f"entradas numéricas divergentes; ausentes={missing}, extras={extra}",
        )
    prepared: dict[str, Any] = {}
    symbolic_dimensions: dict[str, int] = {}
    for name, tensor_type in expected.items():
        dtype = {
            TensorDType.FLOAT32: np.float32,
            TensorDType.FLOAT64: np.float64,
            TensorDType.INT32: np.int32,
            TensorDType.INT64: np.int64,
            TensorDType.BOOL: np.bool_,
        }[tensor_type.dtype]
        value = np.asarray(inputs[name], dtype=dtype)
        if value.ndim != tensor_type.rank:
            raise AutogradError(
                "T6111",
                f"rank inválido para {name}: {value.ndim} != {tensor_type.rank}",
            )
        for actual, declared in zip(value.shape, tensor_type.shape):
            if isinstance(declared, int) and actual != declared:
                raise AutogradError(
                    "T6112",
                    f"shape inválido para {name}: {value.shape} != "
                    f"{tensor_type.shape}",
                )
            if isinstance(declared, str):
                previous = symbolic_dimensions.get(declared)
                if previous is not None and previous != actual:
                    raise AutogradError(
                        "T6117",
                        f"dimensão simbólica {declared} diverge: "
                        f"{previous} != {actual}",
                    )
                symbolic_dimensions[declared] = actual
        prepared[name] = np.array(value, copy=True)
    return prepared


def _execute_forward(
    forward: CrisalidaTensorIR,
    inputs: Mapping[str, Any],
    np: Any,
) -> dict[str, Any]:
    values = {
        name: np.array(value, copy=True)
        for name, value in inputs.items()
    }
    for instruction in forward.instructions:
        arguments = [values[name] for name in instruction.inputs]
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
            result = np.matmul(arguments[0], arguments[1])
        elif operator == "relu":
            result = np.maximum(arguments[0], 0)
        elif operator == "sigmoid":
            result = 1.0 / (1.0 + np.exp(-arguments[0]))
        elif operator == "tanh":
            result = np.tanh(arguments[0])
        elif operator in {"sum", "mean"}:
            reducer = np.sum if operator == "sum" else np.mean
            result = reducer(
                arguments[0],
                axis=attributes.get("axis"),
                keepdims=bool(attributes.get("keepdim", False)),
            )
            if np.ndim(result) == 0:
                result = np.reshape(result, (1,))
        elif operator == "reshape":
            result = np.reshape(arguments[0], tuple(attributes["shape"]))
        elif operator == "transpose":
            result = np.swapaxes(
                arguments[0],
                int(attributes.get("axis0", -2)),
                int(attributes.get("axis1", -1)),
            )
        else:
            raise AutogradError(
                "T6113",
                f"executor de verificação não suporta: {operator}",
            )
        _assert_numeric_shape(
            instruction.result,
            result,
            instruction.output_type,
        )
        values[instruction.result] = result
    return values


def _execute_backward(
    autograd: MetamorfoseAutogradIR,
    forward_values: Mapping[str, Any],
    np: Any,
) -> dict[str, Any]:
    values = dict(forward_values)
    for instruction in autograd.backward:
        arguments = [values[name] for name in instruction.inputs]
        attributes = instruction.attributes
        operator = instruction.operator
        if operator == "ones_like":
            result = np.ones_like(arguments[0])
        elif operator == "zeros_like":
            result = np.zeros_like(arguments[0])
        elif operator == "add":
            result = arguments[0] + arguments[1]
        elif operator == "mul":
            result = arguments[0] * arguments[1]
        elif operator == "div":
            result = arguments[0] / arguments[1]
        elif operator == "neg":
            result = -arguments[0]
        elif operator == "matmul":
            result = np.matmul(arguments[0], arguments[1])
        elif operator == "transpose":
            result = np.swapaxes(
                arguments[0],
                int(attributes.get("axis0", -2)),
                int(attributes.get("axis1", -1)),
            )
        elif operator == "reshape":
            result = np.reshape(arguments[0], tuple(attributes["shape"]))
        elif operator == "reduce_to_shape":
            result = _numeric_reduce_to_shape(
                arguments[0],
                arguments[1].shape,
                np,
            )
        elif operator == "relu_backward":
            result = arguments[0] * (arguments[1] > 0)
        elif operator == "sigmoid_backward":
            result = arguments[0] * arguments[2] * (1.0 - arguments[2])
        elif operator == "tanh_backward":
            result = arguments[0] * (1.0 - arguments[2] * arguments[2])
        elif operator in {"sum_backward", "mean_backward"}:
            gradient, source = arguments
            axis = attributes.get("axis")
            keepdim = bool(attributes.get("keepdim", False))
            if axis is not None and not keepdim:
                gradient = np.expand_dims(gradient, int(axis))
            result = np.broadcast_to(gradient, source.shape)
            if operator == "mean_backward":
                divisor = source.size if axis is None else source.shape[int(axis)]
                result = result / divisor
        else:
            raise AutogradError(
                "T6114",
                f"executor backward não suporta: {operator}",
            )
        _assert_numeric_shape(
            instruction.result,
            result,
            instruction.output_type,
        )
        values[instruction.result] = result
    return values


def _numeric_reduce_to_shape(value: Any, target: tuple[int, ...], np: Any) -> Any:
    result = value
    while result.ndim > len(target):
        result = np.sum(result, axis=0)
    for axis, (actual, expected) in enumerate(zip(result.shape, target)):
        if expected == 1 and actual != 1:
            result = np.sum(result, axis=axis, keepdims=True)
        elif actual != expected:
            raise AutogradError(
                "T6115",
                f"não é possível reduzir shape {value.shape} para {target}",
            )
    return np.reshape(result, target)


def _assert_numeric_shape(
    name: str,
    value: Any,
    tensor_type: LarvaTensor,
) -> None:
    if value.ndim != tensor_type.rank:
        raise AutogradError(
            "T6118",
            f"executor produziu rank inválido para {name}: "
            f"{value.ndim} != {tensor_type.rank}",
        )
    for actual, declared in zip(value.shape, tensor_type.shape):
        if isinstance(declared, int) and actual != declared:
            raise AutogradError(
                "T6119",
                f"executor produziu shape inválido para {name}: "
                f"{value.shape} != {tensor_type.shape}",
            )


def _loss_value(
    autograd: MetamorfoseAutogradIR,
    inputs: Mapping[str, Any],
    np: Any,
) -> float:
    values = _execute_forward(autograd.forward, inputs, np)
    loss = values[autograd.loss]
    if loss.size != 1:
        raise AutogradError("T6116", "loss numérica deixou de ser escalar")
    return float(np.ravel(loss)[0])
