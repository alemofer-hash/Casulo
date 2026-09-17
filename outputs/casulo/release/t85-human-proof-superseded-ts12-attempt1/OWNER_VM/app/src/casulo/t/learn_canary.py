from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .learn_native import LearnNativePlan


CANARY_MAGIC = b"TCANARY\0"
CANARY_MAJOR = 1
CANARY_MINOR = 0
CANARY_RECORDS = 8
CANARY_TOLERANCE = 1e-9
# magic, version, header bytes, dimensions/bounds, then the scalar contract.
CANARY_HEADER = struct.Struct("<8sHH7Iddddd")
CANARY_PROTOCOL = "casulo-learn-numerical-canary/1.0"


class LearnCanaryError(ValueError):
    """The bounded numerical canary is malformed or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class LearnCanary:
    records: int
    input_features: int
    hidden_features: int
    output_features: int
    epochs: int
    parameter_count: int
    learning_rate: float
    target_loss: float
    tolerance: float
    expected_initial_loss: float
    expected_final_loss: float
    inputs: tuple[float, ...]
    targets: tuple[float, ...]
    initial_parameters: tuple[float, ...]
    expected_final_parameters: tuple[float, ...]

    def to_bytes(self) -> bytes:
        scalars = (
            *self.inputs,
            *self.targets,
            *self.initial_parameters,
            *self.expected_final_parameters,
        )
        return CANARY_HEADER.pack(
            CANARY_MAGIC,
            CANARY_MAJOR,
            CANARY_MINOR,
            CANARY_HEADER.size,
            self.records,
            self.input_features,
            self.hidden_features,
            self.output_features,
            self.epochs,
            self.parameter_count,
            self.learning_rate,
            self.target_loss,
            self.tolerance,
            self.expected_initial_loss,
            self.expected_final_loss,
        ) + struct.pack(f"<{len(scalars)}d", *scalars)


@dataclass(frozen=True, slots=True)
class CanaryResult:
    initial_loss: float
    final_loss: float
    parameters: tuple[float, ...]


def build_flood_canary(plan: LearnNativePlan) -> LearnCanary:
    """Build a small correctness fixture, never a performance workload.

    The data and initialization use closed integer formulas instead of a PRNG,
    so no library-specific random stream is part of the ABI.  Expected values
    are computed by the scalar reference implementation using the loop order
    frozen in ``LEARN_CONTEXT_ABI_V1.md``.
    """

    if (plan.input_features, plan.hidden_features, plan.output_features) != (
        8,
        8,
        1,
    ):
        raise LearnCanaryError("canary v1 requires the declared 8x8x1 topology")
    if plan.precision != "float64" or plan.batch != "full":
        raise LearnCanaryError("canary v1 requires float64 full-batch semantics")
    if plan.activation != "relu" or plan.loss != "mse" or plan.optimizer != "sgd":
        raise LearnCanaryError("canary v1 requires relu/mse/sgd")

    inputs = tuple(
        (((record + 1) * (feature + 3)) % 11 - 5) / 10.0
        for record in range(CANARY_RECORDS)
        for feature in range(plan.input_features)
    )
    targets = tuple(
        0.8
        + sum(
            (feature + 1) * inputs[record * plan.input_features + feature]
            for feature in range(plan.input_features)
        )
        / 20.0
        for record in range(CANARY_RECORDS)
    )
    weights_1 = tuple(
        0.12
        if feature == hidden
        else 0.01 * ((feature + hidden) % 3 - 1)
        for feature in range(plan.input_features)
        for hidden in range(plan.hidden_features)
    )
    bias_1 = tuple(0.25 + 0.01 * hidden for hidden in range(plan.hidden_features))
    weights_2 = tuple(
        0.04 * ((hidden % 3) + 1) for hidden in range(plan.hidden_features)
    )
    initial = (*weights_1, *bias_1, *weights_2, 0.05)
    result = execute_scalar(
        inputs=inputs,
        targets=targets,
        initial_parameters=initial,
        records=CANARY_RECORDS,
        input_features=plan.input_features,
        hidden_features=plan.hidden_features,
        epochs=plan.epochs,
        learning_rate=plan.learning_rate,
    )
    if result.initial_loss <= plan.target_loss:
        raise LearnCanaryError("canary must begin above the declared quality target")
    if result.final_loss > plan.target_loss:
        raise LearnCanaryError("canary does not attain the declared quality target")
    return LearnCanary(
        records=CANARY_RECORDS,
        input_features=plan.input_features,
        hidden_features=plan.hidden_features,
        output_features=plan.output_features,
        epochs=plan.epochs,
        parameter_count=len(initial),
        learning_rate=plan.learning_rate,
        target_loss=plan.target_loss,
        tolerance=CANARY_TOLERANCE,
        expected_initial_loss=result.initial_loss,
        expected_final_loss=result.final_loss,
        inputs=inputs,
        targets=targets,
        initial_parameters=tuple(initial),
        expected_final_parameters=result.parameters,
    )


def parse_flood_canary(raw: bytes) -> LearnCanary:
    if len(raw) < CANARY_HEADER.size:
        raise LearnCanaryError("canary is truncated before its header")
    unpacked = CANARY_HEADER.unpack_from(raw)
    (
        magic,
        major,
        minor,
        header_bytes,
        records,
        input_features,
        hidden_features,
        output_features,
        epochs,
        parameter_count,
        learning_rate,
        target_loss,
        tolerance,
        expected_initial_loss,
        expected_final_loss,
    ) = unpacked
    if magic != CANARY_MAGIC or (major, minor) != (CANARY_MAJOR, CANARY_MINOR):
        raise LearnCanaryError("unsupported canary magic or version")
    if header_bytes != CANARY_HEADER.size:
        raise LearnCanaryError("canary header size differs from ABI")
    if (records, input_features, hidden_features, output_features) != (8, 8, 8, 1):
        raise LearnCanaryError("canary dimensions exceed or differ from v1 bounds")
    expected_parameters = input_features * hidden_features + hidden_features * 2 + 1
    if parameter_count != expected_parameters or epochs == 0 or epochs > 4096:
        raise LearnCanaryError("canary execution bounds are invalid")
    if not all(
        math.isfinite(item)
        for item in (
            learning_rate,
            target_loss,
            tolerance,
            expected_initial_loss,
            expected_final_loss,
        )
    ) or learning_rate <= 0.0 or target_loss < 0.0 or tolerance <= 0.0:
        raise LearnCanaryError("canary scalar contract is invalid")
    scalar_count = records * input_features + records + parameter_count * 2
    expected_length = CANARY_HEADER.size + scalar_count * 8
    if len(raw) != expected_length:
        raise LearnCanaryError("canary payload length differs from dimensions")
    values = struct.unpack_from(f"<{scalar_count}d", raw, CANARY_HEADER.size)
    if not all(math.isfinite(item) for item in values):
        raise LearnCanaryError("canary arrays contain non-finite float64")
    cursor = 0
    inputs = values[cursor : cursor + records * input_features]
    cursor += records * input_features
    targets = values[cursor : cursor + records]
    cursor += records
    initial = values[cursor : cursor + parameter_count]
    cursor += parameter_count
    expected = values[cursor : cursor + parameter_count]
    return LearnCanary(
        records=records,
        input_features=input_features,
        hidden_features=hidden_features,
        output_features=output_features,
        epochs=epochs,
        parameter_count=parameter_count,
        learning_rate=learning_rate,
        target_loss=target_loss,
        tolerance=tolerance,
        expected_initial_loss=expected_initial_loss,
        expected_final_loss=expected_final_loss,
        inputs=tuple(inputs),
        targets=tuple(targets),
        initial_parameters=tuple(initial),
        expected_final_parameters=tuple(expected),
    )


def execute_scalar(
    *,
    inputs: tuple[float, ...],
    targets: tuple[float, ...],
    initial_parameters: tuple[float, ...],
    records: int,
    input_features: int,
    hidden_features: int,
    epochs: int,
    learning_rate: float,
) -> CanaryResult:
    """Literal scalar oracle matching the native payload's loop nesting."""

    parameters = list(initial_parameters)
    parameter_count = input_features * hidden_features + hidden_features * 2 + 1
    if len(parameters) != parameter_count:
        raise LearnCanaryError("initial parameter count differs from topology")

    def evaluate() -> float:
        total = 0.0
        for record in range(records):
            prediction = _predict_scalar(
                inputs, record * input_features, parameters, input_features, hidden_features
            )
            error = prediction - targets[record]
            total += error * error
        return total / float(records)

    initial_loss = evaluate()
    b1 = input_features * hidden_features
    w2 = b1 + hidden_features
    b2 = w2 + hidden_features
    for _epoch in range(epochs):
        gradients = [0.0] * parameter_count
        for record in range(records):
            row = record * input_features
            pre = [parameters[b1 + hidden] for hidden in range(hidden_features)]
            for feature in range(input_features):
                value = inputs[row + feature]
                for hidden in range(hidden_features):
                    pre[hidden] += value * parameters[feature * hidden_features + hidden]
            hidden_values = [0.0] * hidden_features
            prediction = parameters[b2]
            for hidden in range(hidden_features):
                hidden_values[hidden] = pre[hidden] if pre[hidden] > 0.0 else 0.0
                prediction += hidden_values[hidden] * parameters[w2 + hidden]
            output_gradient = (2.0 / float(records)) * (prediction - targets[record])
            gradients[b2] += output_gradient
            delta = [0.0] * hidden_features
            for hidden in range(hidden_features):
                derivative = 1.0 if pre[hidden] > 0.0 else 0.0
                delta[hidden] = output_gradient * parameters[w2 + hidden] * derivative
                gradients[w2 + hidden] += output_gradient * hidden_values[hidden]
                gradients[b1 + hidden] += delta[hidden]
            for feature in range(input_features):
                value = inputs[row + feature]
                for hidden in range(hidden_features):
                    gradients[feature * hidden_features + hidden] += delta[hidden] * value
        for parameter in range(parameter_count):
            parameters[parameter] -= learning_rate * gradients[parameter]
    return CanaryResult(initial_loss, evaluate(), tuple(parameters))


def execute_audit(canary: LearnCanary) -> CanaryResult:
    """Independent host reimplementation used by the verifier.

    This intentionally does not call ``execute_scalar`` or its prediction
    helper.  It uses index-controlled while loops mirroring the ABI document,
    providing a second implementation while retaining the declared float64
    operation order.
    """

    n, width, hidden_count = (
        canary.records,
        canary.input_features,
        canary.hidden_features,
    )
    parameters = list(canary.initial_parameters)
    b1 = width * hidden_count
    w2 = b1 + hidden_count
    b2 = w2 + hidden_count

    def audit_loss() -> float:
        total = 0.0
        record = 0
        while record < n:
            hidden_values = [parameters[b1 + j] for j in range(hidden_count)]
            feature = 0
            while feature < width:
                value = canary.inputs[record * width + feature]
                hidden = 0
                while hidden < hidden_count:
                    hidden_values[hidden] += value * parameters[feature * hidden_count + hidden]
                    hidden += 1
                feature += 1
            prediction = parameters[b2]
            hidden = 0
            while hidden < hidden_count:
                active = hidden_values[hidden] if hidden_values[hidden] > 0.0 else 0.0
                prediction += active * parameters[w2 + hidden]
                hidden += 1
            error = prediction - canary.targets[record]
            total += error * error
            record += 1
        return total / float(n)

    initial_loss = audit_loss()
    epoch = 0
    while epoch < canary.epochs:
        gradients = [0.0] * canary.parameter_count
        record = 0
        while record < n:
            pre = [parameters[b1 + j] for j in range(hidden_count)]
            feature = 0
            while feature < width:
                value = canary.inputs[record * width + feature]
                hidden = 0
                while hidden < hidden_count:
                    pre[hidden] += value * parameters[feature * hidden_count + hidden]
                    hidden += 1
                feature += 1
            activated = [0.0] * hidden_count
            prediction = parameters[b2]
            hidden = 0
            while hidden < hidden_count:
                activated[hidden] = pre[hidden] if pre[hidden] > 0.0 else 0.0
                prediction += activated[hidden] * parameters[w2 + hidden]
                hidden += 1
            output_gradient = (2.0 / float(n)) * (prediction - canary.targets[record])
            gradients[b2] += output_gradient
            deltas = [0.0] * hidden_count
            hidden = 0
            while hidden < hidden_count:
                derivative = 1.0 if pre[hidden] > 0.0 else 0.0
                deltas[hidden] = output_gradient * parameters[w2 + hidden] * derivative
                gradients[w2 + hidden] += output_gradient * activated[hidden]
                gradients[b1 + hidden] += deltas[hidden]
                hidden += 1
            feature = 0
            while feature < width:
                value = canary.inputs[record * width + feature]
                hidden = 0
                while hidden < hidden_count:
                    gradients[feature * hidden_count + hidden] += deltas[hidden] * value
                    hidden += 1
                feature += 1
            record += 1
        parameter = 0
        while parameter < canary.parameter_count:
            parameters[parameter] -= canary.learning_rate * gradients[parameter]
            parameter += 1
        epoch += 1
    return CanaryResult(initial_loss, audit_loss(), tuple(parameters))


def verify_canary_oracle(canary: LearnCanary) -> dict[str, float | int | str]:
    result = execute_audit(canary)
    max_abs = max(
        abs(actual - expected)
        for actual, expected in zip(result.parameters, canary.expected_final_parameters)
    )
    initial_difference = abs(result.initial_loss - canary.expected_initial_loss)
    final_difference = abs(result.final_loss - canary.expected_final_loss)
    if max(max_abs, initial_difference, final_difference) > canary.tolerance:
        raise LearnCanaryError("independent audit oracle differs from embedded expectations")
    if result.final_loss > canary.target_loss:
        raise LearnCanaryError("independent audit result misses the quality target")
    return {
        "protocol": CANARY_PROTOCOL,
        "records": canary.records,
        "epochs": canary.epochs,
        "initial_loss": result.initial_loss,
        "final_loss": result.final_loss,
        "target_loss": canary.target_loss,
        "tolerance": canary.tolerance,
        "max_abs_parameter_difference": max_abs,
    }


def _predict_scalar(
    inputs: tuple[float, ...],
    row: int,
    parameters: list[float],
    input_features: int,
    hidden_features: int,
) -> float:
    b1 = input_features * hidden_features
    w2 = b1 + hidden_features
    b2 = w2 + hidden_features
    hidden_values = [parameters[b1 + hidden] for hidden in range(hidden_features)]
    for feature in range(input_features):
        value = inputs[row + feature]
        for hidden in range(hidden_features):
            hidden_values[hidden] += value * parameters[feature * hidden_features + hidden]
    output = parameters[b2]
    for hidden in range(hidden_features):
        active = hidden_values[hidden] if hidden_values[hidden] > 0.0 else 0.0
        output += active * parameters[w2 + hidden]
    return output
