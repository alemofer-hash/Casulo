from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import mmap
import platform
import time
from pathlib import Path

from casulo.t.learn_canary import LearnCanary, parse_flood_canary
from casulo.t.tcap import load_tcap

from .energy_v1.paired_runner import UNIT_RESULT_SCHEMA
from .energy_v1.schemas import canonical_bytes, sha256_bytes


SEMANTIC_SCOPE = ("forward", "mse_loss", "backward", "sgd_update")


class LearnContext(ctypes.Structure):
    _fields_ = [
        ("inputs", ctypes.POINTER(ctypes.c_double)),
        ("targets", ctypes.POINTER(ctypes.c_double)),
        ("parameters", ctypes.POINTER(ctypes.c_double)),
        ("gradients", ctypes.POINTER(ctypes.c_double)),
        ("records", ctypes.c_size_t),
        ("epochs", ctypes.c_size_t),
        ("learning_rate", ctypes.c_double),
        ("initial_loss", ctypes.POINTER(ctypes.c_double)),
        ("final_loss", ctypes.POINTER(ctypes.c_double)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One complete, reset Casulo Energy V1 training unit.")
    parser.add_argument("--implementation", choices=("t-general-ir-tcap/0.1", "pytorch-eager-fullstep/1", "pytorch-compile-fullstep/1"), required=True)
    parser.add_argument("--tcap", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic_ns()
    package = load_tcap(args.tcap)
    segments = {item.name: item.data for item in package.segments}
    canary_raw = segments["canary"]
    canary = parse_flood_canary(canary_raw)
    initialized = time.monotonic_ns()
    if args.implementation == "t-general-ir-tcap/0.1":
        initial_loss, final_loss, parameters = _execute_raw_tcap(segments["code"], canary)
        compilation_seconds = 0.0
    else:
        initial_loss, final_loss, parameters, compilation_seconds = _execute_pytorch(
            canary, compile_step=args.implementation == "pytorch-compile-fullstep/1"
        )
    executed = time.monotonic_ns()
    predictions = _predictions(canary, parameters)
    numeric = [initial_loss, final_loss, *parameters, *predictions]
    if not all(math.isfinite(item) for item in numeric):
        raise SystemExit("non-finite unit output")
    output = {
        "schema": UNIT_RESULT_SCHEMA,
        "status": "PASS",
        "implementation": args.implementation,
        "workload": "flood-surrogate-canary-400",
        "dataset_sha256": hashlib.sha256(canary_raw).hexdigest(),
        "semantic_scope": list(SEMANTIC_SCOPE),
        "loss": {"initial": initial_loss, "final": final_loss},
        "parameters": list(parameters),
        "predictions": list(predictions),
        "numeric_output": numeric,
        "output_sha256": sha256_bytes(canonical_bytes(numeric)),
        "phases_seconds": {
            "initialization": (initialized - started) / 1e9,
            "compilation": compilation_seconds,
            "warmup": 0.0,
            "stationary_execution": max(0.0, (executed - initialized) / 1e9 - compilation_seconds),
            "shutdown": 0.0,
        },
        "fresh_mathematical_state": True,
        "epochs": canary.epochs,
        "records": canary.records,
        "precision": "float64",
        "seed": "closed-form-canary-v1",
    }
    print(json.dumps(output, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    return 0


def _execute_raw_tcap(code: bytes, canary: LearnCanary) -> tuple[float, float, tuple[float, ...]]:
    if platform.system().lower() != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("raw TCAP energy unit requires bare-metal Linux x86-64")
    allocation = mmap.mmap(-1, len(code), flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS, prot=mmap.PROT_READ | mmap.PROT_WRITE)
    view = (ctypes.c_ubyte * len(code)).from_buffer(allocation)
    address = ctypes.addressof(view)
    ctypes.memmove(address, code, len(code))
    page = mmap.PAGESIZE
    base = address & ~(page - 1)
    span = ((address + len(code) - base + page - 1) // page) * page
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.mprotect(ctypes.c_void_p(base), ctypes.c_size_t(span), mmap.PROT_READ | mmap.PROT_EXEC) != 0:
        error = ctypes.get_errno()
        del view
        allocation.close()
        raise OSError(error, "mprotect RX failed")
    inputs = (ctypes.c_double * len(canary.inputs))(*canary.inputs)
    targets = (ctypes.c_double * len(canary.targets))(*canary.targets)
    parameters = (ctypes.c_double * len(canary.initial_parameters))(*canary.initial_parameters)
    gradients = (ctypes.c_double * canary.parameter_count)()
    initial_loss = ctypes.c_double()
    final_loss = ctypes.c_double()
    context = LearnContext(inputs, targets, parameters, gradients, canary.records, canary.epochs, canary.learning_rate, ctypes.pointer(initial_loss), ctypes.pointer(final_loss))
    entry_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(LearnContext))
    entry = entry_type(address)
    try:
        result = entry(ctypes.byref(context))
        values = tuple(float(item) for item in parameters)
    finally:
        del entry
        del view
        allocation.close()
    if result != 0:
        raise RuntimeError(f"TCAP entry returned {result}")
    maximum = max(abs(a - b) for a, b in zip(values, canary.expected_final_parameters))
    if abs(initial_loss.value - canary.expected_initial_loss) > canary.tolerance or abs(final_loss.value - canary.expected_final_loss) > canary.tolerance or maximum > canary.tolerance:
        raise RuntimeError("raw TCAP output differs from its frozen canary")
    return initial_loss.value, final_loss.value, values


def _execute_pytorch(canary: LearnCanary, *, compile_step: bool) -> tuple[float, float, tuple[float, ...], float]:
    import torch

    torch.set_default_dtype(torch.float64)
    x = torch.tensor(canary.inputs, dtype=torch.float64).reshape(canary.records, canary.input_features)
    y = torch.tensor(canary.targets, dtype=torch.float64).reshape(canary.records)
    p = canary.initial_parameters
    f, h = canary.input_features, canary.hidden_features
    p0, p1, p2 = f * h, f * h + h, f * h + h + h
    parameters = {
        "w1": torch.tensor(p[:p0], requires_grad=True).reshape(f, h),
        "b1": torch.tensor(p[p0:p1], requires_grad=True),
        "w2": torch.tensor(p[p1:p2], requires_grad=True),
        "b2": torch.tensor([p[p2]], requires_grad=True),
    }
    # reshape creates non-leaf w1; retain a leaf parameter with identical bits.
    parameters["w1"] = parameters["w1"].detach().clone().requires_grad_(True)

    def forward_loss(w1, b1, w2, b2):
        prediction = torch.relu(x @ w1 + b1) @ w2 + b2[0]
        return torch.mean((prediction - y) ** 2)

    initial = float(forward_loss(**parameters).detach())

    def step(w1, b1, w2, b2):
        loss = forward_loss(w1, b1, w2, b2)
        grads = torch.autograd.grad(loss, (w1, b1, w2, b2), create_graph=False)
        return tuple(value - canary.learning_rate * grad for value, grad in zip((w1, b1, w2, b2), grads))

    compilation = 0.0
    compiled = step
    if compile_step:
        before = time.monotonic_ns()
        compiled = torch.compile(step, fullgraph=True)
        # Compilation happens on first call and is explicitly included.
        parameters = dict(zip(parameters, compiled(**parameters)))
        compilation = (time.monotonic_ns() - before) / 1e9
        remaining = canary.epochs - 1
    else:
        remaining = canary.epochs
    for _ in range(remaining):
        parameters = dict(zip(parameters, compiled(**parameters)))
    final = float(forward_loss(**parameters).detach())
    ordered = (
        *parameters["w1"].detach().reshape(-1).tolist(),
        *parameters["b1"].detach().reshape(-1).tolist(),
        *parameters["w2"].detach().reshape(-1).tolist(),
        *parameters["b2"].detach().reshape(-1).tolist(),
    )
    return initial, final, tuple(float(item) for item in ordered), compilation


def _predictions(canary: LearnCanary, parameters: tuple[float, ...]) -> tuple[float, ...]:
    f, h = canary.input_features, canary.hidden_features
    p0, p1, p2 = f * h, f * h + h, f * h + h + h
    w1, b1, w2, b2 = parameters[:p0], parameters[p0:p1], parameters[p1:p2], parameters[p2]
    output = []
    for record in range(canary.records):
        hidden = []
        for unit in range(h):
            value = b1[unit]
            for feature in range(f):
                value += canary.inputs[record * f + feature] * w1[feature * h + unit]
            hidden.append(max(0.0, value))
        prediction = b2
        for unit in range(h):
            prediction += hidden[unit] * w2[unit]
        output.append(prediction)
    return tuple(output)


if __name__ == "__main__":
    raise SystemExit(main())
