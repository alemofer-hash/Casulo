from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


class BaselineUnavailable(RuntimeError):
    """The requested baseline cannot be represented without weakening it."""


@dataclass(frozen=True, slots=True)
class FullStepMetadata:
    adapter: str
    backend: str
    compiled: bool
    fullgraph: bool
    included_operations: tuple[str, ...]
    optimizer: str
    precision: str


@dataclass(slots=True)
class PyTorchFullStep:
    """Functional PyTorch baseline containing forward, backward and SGD.

    Parameters are explicit state. This avoids measuring Python ``Optimizer``
    orchestration while the candidate measures a fused step, and lets
    ``torch.compile(fullgraph=True)`` reject rather than silently graph-break.
    Only plain SGD without momentum/weight decay is represented in v1.
    """

    run: Callable[[Mapping[str, Any], Mapping[str, Any], Any, Any], tuple[dict[str, Any], Any]]
    parameters: dict[str, Any]
    buffers: dict[str, Any]
    metadata: FullStepMetadata

    def step(self, inputs: Any, targets: Any) -> Any:
        self.parameters, loss = self.run(self.parameters, self.buffers, inputs, targets)
        return loss


def build_pytorch_full_step(
    model: Any,
    loss_function: Callable[[Any, Any], Any],
    *,
    learning_rate: float,
    compile_step: bool,
    backend: str = "inductor",
    torch_module: Any | None = None,
) -> PyTorchFullStep:
    if not 0.0 < learning_rate < 1.0:
        raise ValueError("learning_rate must be in (0, 1)")
    torch = torch_module
    if torch is None:
        try:
            import torch as imported_torch
        except ImportError as exc:
            raise BaselineUnavailable("PyTorch is not installed") from exc
        torch = imported_torch
    try:
        functional_call = torch.func.functional_call
        grad_and_value = torch.func.grad_and_value
    except AttributeError as exc:
        raise BaselineUnavailable("PyTorch torch.func is unavailable") from exc

    parameters = {name: value.detach().clone() for name, value in model.named_parameters()}
    buffers = {name: value.detach().clone() for name, value in model.named_buffers()}
    if not parameters:
        raise BaselineUnavailable("model has no trainable parameters")

    def full_step(
        current: Mapping[str, Any],
        current_buffers: Mapping[str, Any],
        inputs: Any,
        targets: Any,
    ) -> tuple[dict[str, Any], Any]:
        def objective(candidate: Mapping[str, Any]) -> Any:
            predictions = functional_call(model, (candidate, current_buffers), (inputs,))
            return loss_function(predictions, targets)

        gradients, loss = grad_and_value(objective)(current)
        updated = {
            # Plain SGD creates fresh leaf state between steps. Detaching here
            # prevents an accidental graph spanning the complete training run.
            name: (value - learning_rate * gradients[name]).detach()
            for name, value in current.items()
        }
        return updated, loss

    runner = full_step
    if compile_step:
        compiler = getattr(torch, "compile", None)
        if compiler is None:
            raise BaselineUnavailable("torch.compile is unavailable")
        try:
            runner = compiler(full_step, backend=backend, fullgraph=True)
        except Exception as exc:
            raise BaselineUnavailable(f"full-step torch.compile is unavailable: {exc}") from exc
    dtype = next(iter(parameters.values())).dtype
    metadata = FullStepMetadata(
        adapter="casulo-livelab-pytorch-full-step/1",
        backend=backend if compile_step else "eager",
        compiled=compile_step,
        fullgraph=compile_step,
        included_operations=("forward", "loss", "backward", "sgd_update"),
        optimizer="SGD(lr, momentum=0, weight_decay=0)",
        precision=str(dtype),
    )
    return PyTorchFullStep(runner, parameters, buffers, metadata)
