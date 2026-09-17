from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Mapping


LEARN_CONTRACT_PROTOCOL = "casulo-learn-contract/0.2"
LEARN_PROPERTY_NAMES = frozenset(
    {
        "input_features",
        "hidden_features",
        "output_features",
        "activation",
        "loss",
        "optimizer",
        "learning_rate",
        "epochs",
        "precision",
        "batch",
        "seed",
        "target_loss",
    }
)


class LearnContractError(ValueError):
    """Contrato declarativo `learn` inválido."""


@dataclass(frozen=True, slots=True)
class LearnSemanticContract:
    """Forma tipada, dimensionada e auditável de uma declaração `learn`.

    O contrato descreve o subconjunto executável atual. Ele não afirma que a
    linguagem geral já suporte arquiteturas arbitrárias.
    """

    protocol: str
    module: str
    name: str
    input_features: int
    hidden_features: int
    output_features: int
    activation: str
    loss: str
    optimizer: str
    learning_rate: float
    epochs: int
    precision: str
    batch: str
    seed: int
    target_loss: float
    input_shape: tuple[str | int, ...]
    hidden_shape: tuple[str | int, ...]
    output_shape: tuple[str | int, ...]
    parameter_shapes: tuple[tuple[str, tuple[int, ...]], ...]
    effects: tuple[str, ...]
    permissions: tuple[str, ...]
    deterministic: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_learn_contract(
    *,
    module: str | None,
    name: str,
    values: Mapping[str, str],
) -> LearnSemanticContract:
    if module is None:
        raise LearnContractError("module e learn são obrigatórios")

    unknown = set(values) - LEARN_PROPERTY_NAMES
    missing = LEARN_PROPERTY_NAMES - set(values)
    if unknown:
        raise LearnContractError(
            "propriedades desconhecidas: " + ", ".join(sorted(unknown))
        )
    if missing:
        raise LearnContractError("propriedades ausentes: " + ", ".join(sorted(missing)))

    try:
        input_features = int(values["input_features"])
        hidden_features = int(values["hidden_features"])
        output_features = int(values["output_features"])
        learning_rate = float(values["learning_rate"])
        epochs = int(values["epochs"])
        seed = int(values["seed"])
        target_loss = float(values["target_loss"])
    except ValueError as error:
        raise LearnContractError(f"valor numérico inválido: {error}") from error

    if not 1 <= input_features <= 64:
        raise LearnContractError("input_features precisa estar entre 1 e 64")
    if not 1 <= hidden_features <= 256:
        raise LearnContractError("hidden_features precisa estar entre 1 e 256")
    if output_features != 1:
        raise LearnContractError("backend 0.1 aceita exatamente uma saída")
    activation = values["activation"]
    if activation not in {"tanh", "relu"}:
        raise LearnContractError("activation precisa ser tanh ou relu")
    loss = values["loss"]
    optimizer = values["optimizer"]
    if loss != "mse" or optimizer != "sgd":
        raise LearnContractError("backend 0.1 exige loss mse e optimizer sgd")
    precision = values["precision"]
    batch = values["batch"]
    if precision != "float64" or batch != "full":
        raise LearnContractError("backend 0.1 exige precision float64 e batch full")
    if not math.isfinite(learning_rate) or learning_rate <= 0:
        raise LearnContractError("learning_rate precisa ser positivo e finito")
    if not 1 <= epochs <= 1_000_000:
        raise LearnContractError("epochs precisa estar entre 1 e 1.000.000")
    if not math.isfinite(target_loss) or target_loss <= 0:
        raise LearnContractError("target_loss precisa ser positivo e finito")

    return LearnSemanticContract(
        protocol=LEARN_CONTRACT_PROTOCOL,
        module=module,
        name=name,
        input_features=input_features,
        hidden_features=hidden_features,
        output_features=output_features,
        activation=activation,
        loss=loss,
        optimizer=optimizer,
        learning_rate=learning_rate,
        epochs=epochs,
        precision=precision,
        batch=batch,
        seed=seed,
        target_loss=target_loss,
        input_shape=("batch", input_features),
        hidden_shape=("batch", hidden_features),
        output_shape=("batch", output_features),
        parameter_shapes=(
            ("weight_input_hidden", (input_features, hidden_features)),
            ("bias_hidden", (hidden_features,)),
            ("weight_hidden_output", (hidden_features, output_features)),
            ("bias_output", (output_features,)),
        ),
        effects=(
            "read:training_data",
            "read:validation_data",
            "write:model_parameters",
            "write:training_metrics",
        ),
        permissions=("cpu.compute", "memory.workspace"),
        deterministic=True,
    )
