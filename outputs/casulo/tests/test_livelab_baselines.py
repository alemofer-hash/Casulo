from __future__ import annotations

import pytest

from casulo.livelab.baselines import build_pytorch_full_step


def test_full_step_eager_matches_stateful_pytorch_sgd() -> None:
    torch = pytest.importorskip("torch")
    torch.manual_seed(123)
    reference = torch.nn.Linear(2, 1, bias=True, dtype=torch.float64)
    candidate = torch.nn.Linear(2, 1, bias=True, dtype=torch.float64)
    candidate.load_state_dict(reference.state_dict())
    inputs = torch.tensor([[1.0, 2.0], [3.0, -1.0]], dtype=torch.float64)
    targets = torch.tensor([[0.5], [1.25]], dtype=torch.float64)
    loss_function = torch.nn.MSELoss()

    optimizer = torch.optim.SGD(reference.parameters(), lr=0.01)
    optimizer.zero_grad(set_to_none=True)
    reference_loss = loss_function(reference(inputs), targets)
    reference_loss.backward()
    optimizer.step()

    full_step = build_pytorch_full_step(
        candidate,
        loss_function,
        learning_rate=0.01,
        compile_step=False,
        torch_module=torch,
    )
    candidate_loss = full_step.step(inputs, targets)
    assert torch.equal(candidate_loss, reference_loss.detach())
    for name, expected in reference.named_parameters():
        assert torch.allclose(full_step.parameters[name], expected, rtol=0, atol=1e-15)
    assert full_step.metadata.included_operations == (
        "forward", "loss", "backward", "sgd_update"
    )
    assert not full_step.metadata.compiled


def test_full_step_does_not_retain_a_graph_across_iterations() -> None:
    torch = pytest.importorskip("torch")
    torch.manual_seed(321)
    reference = torch.nn.Linear(2, 1, dtype=torch.float64)
    candidate = torch.nn.Linear(2, 1, dtype=torch.float64)
    candidate.load_state_dict(reference.state_dict())
    inputs = torch.tensor([[1.0, -2.0], [0.5, 3.0]], dtype=torch.float64)
    targets = torch.tensor([[0.25], [-1.0]], dtype=torch.float64)
    loss_function = torch.nn.MSELoss()
    optimizer = torch.optim.SGD(reference.parameters(), lr=0.01)
    full_step = build_pytorch_full_step(
        candidate,
        loss_function,
        learning_rate=0.01,
        compile_step=False,
        torch_module=torch,
    )
    for _ in range(3):
        optimizer.zero_grad(set_to_none=True)
        loss_function(reference(inputs), targets).backward()
        optimizer.step()
        full_step.step(inputs, targets)
    for name, expected in reference.named_parameters():
        assert torch.allclose(full_step.parameters[name], expected, rtol=0, atol=1e-15)
        assert full_step.parameters[name].grad_fn is None


def test_compile_adapter_requests_fullgraph_without_running_compiler() -> None:
    torch = pytest.importorskip("torch")
    model = torch.nn.Linear(1, 1)
    observed: dict[str, object] = {}

    class TorchProxy:
        func = torch.func

        @staticmethod
        def compile(function, **kwargs):
            observed.update(kwargs)
            return function

    baseline = build_pytorch_full_step(
        model,
        torch.nn.MSELoss(),
        learning_rate=0.1,
        compile_step=True,
        torch_module=TorchProxy,
    )
    assert observed == {"backend": "inductor", "fullgraph": True}
    assert baseline.metadata.compiled
    assert baseline.metadata.fullgraph
