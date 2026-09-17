from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from .baselines import BaselineUnavailable, build_pytorch_full_step
from .workloads import GeneratedWorkload, WorkloadSpec, generate_workload, get_workload


ADAPTER_PROTOCOL = "casulo-livelab-smoke-adapter/1.0"


class AdapterStatus(StrEnum):
    PASS = "PASS"
    UNAVAILABLE = "UNAVAILABLE"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class AdapterResult:
    adapter: str
    workload: str
    status: AdapterStatus
    semantic_scope: tuple[str, ...]
    data_sha256: str
    output_sha256: str | None
    output_count: int
    details: dict[str, Any]
    numeric_output: tuple[float, ...] = ()
    protocol: str = ADAPTER_PROTOCOL

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value.pop("numeric_output")
        return value


@dataclass(frozen=True, slots=True)
class EquivalenceResult:
    status: AdapterStatus
    reason: str
    maximum_absolute_error: float | None
    maximum_relative_error: float | None


Adapter = Callable[[WorkloadSpec, GeneratedWorkload, bool], AdapterResult]


def available_adapters() -> tuple[str, ...]:
    return tuple(_ADAPTERS)


def run_smoke_adapter(
    adapter: str,
    workload: str | WorkloadSpec,
    *,
    allow_toolchain: bool = False,
) -> AdapterResult:
    spec = get_workload(workload) if isinstance(workload, str) else workload
    try:
        implementation = _ADAPTERS[adapter]
    except KeyError as exc:
        raise KeyError(f"unknown adapter: {adapter}") from exc
    data = generate_workload(spec, profile="smoke")
    try:
        return implementation(spec, data, allow_toolchain)
    except BaselineUnavailable as exc:
        return _unavailable(adapter, spec, data, str(exc))
    except (ImportError, ModuleNotFoundError) as exc:
        return _unavailable(adapter, spec, data, f"dependency unavailable: {exc}")
    except Exception as exc:
        # A supported adapter error is evidence of failure, not availability.
        return AdapterResult(
            adapter, spec.identity, AdapterStatus.FAIL,
            spec.operation_expectations, data.sha256, None, 0,
            {"error_type": type(exc).__name__, "error": str(exc), "performance_measured": False},
        )


def compare_equivalence(
    reference: AdapterResult,
    candidate: AdapterResult,
    spec: WorkloadSpec,
) -> EquivalenceResult:
    if reference.status is not AdapterStatus.PASS or candidate.status is not AdapterStatus.PASS:
        return EquivalenceResult(AdapterStatus.UNAVAILABLE, "both adapters must PASS", None, None)
    if reference.semantic_scope != candidate.semantic_scope or reference.data_sha256 != candidate.data_sha256:
        return EquivalenceResult(AdapterStatus.FAIL, "semantic scope or data differs", None, None)
    if len(reference.numeric_output) != len(candidate.numeric_output):
        return EquivalenceResult(AdapterStatus.FAIL, "output cardinality differs", None, None)
    absolute = 0.0
    relative = 0.0
    for expected, observed in zip(reference.numeric_output, candidate.numeric_output, strict=True):
        if not math.isfinite(expected) or not math.isfinite(observed):
            return EquivalenceResult(AdapterStatus.FAIL, "non-finite output", None, None)
        delta = abs(expected - observed)
        absolute = max(absolute, delta)
        relative = max(relative, delta / max(abs(expected), abs(observed), 1e-30))
    allowed_abs = float(spec.quality["absolute_tolerance"])
    allowed_rel = float(spec.quality["relative_tolerance"])
    status = AdapterStatus.PASS if absolute <= allowed_abs or relative <= allowed_rel else AdapterStatus.FAIL
    return EquivalenceResult(status, "within frozen tolerance" if status is AdapterStatus.PASS else "outside frozen tolerance", absolute, relative)


def _numpy_semantic(spec: WorkloadSpec, data: GeneratedWorkload, _: bool) -> AdapterResult:
    try:
        import numpy as np
    except ImportError as exc:
        raise BaselineUnavailable("NumPy is not installed") from exc
    output = _numpy_reference(spec, data, np)
    return _passed("numpy-semantic/1", spec, data, output, {"implementation": "explicit semantic reference", "blas_required": False})


def _numpy_blas(spec: WorkloadSpec, data: GeneratedWorkload, _: bool) -> AdapterResult:
    if spec.family not in {"dense-mlp", "attention"}:
        return _unavailable("numpy-blas/1", spec, data, "workload has no semantically equivalent BLAS formulation")
    try:
        import numpy as np
    except ImportError as exc:
        raise BaselineUnavailable("NumPy is not installed") from exc
    output = _numpy_reference(spec, data, np)
    configuration = getattr(np, "__config__", None)
    return _passed(
        "numpy-blas/1", spec, data, output,
        {"implementation": "NumPy matmul BLAS regime", "numpy_version": np.__version__, "blas_configuration_exposed": configuration is not None},
    )


def _pytorch(spec: WorkloadSpec, data: GeneratedWorkload, compile_step: bool) -> AdapterResult:
    if spec.family != "dense-mlp":
        return _unavailable(
            "pytorch-compile-fullstep/1" if compile_step else "pytorch-eager-fullstep/1",
            spec, data, "v1 full-step adapter supports dense MLP only; forward-only substitution is forbidden",
        )
    try:
        import torch
    except ImportError as exc:
        raise BaselineUnavailable("PyTorch is not installed") from exc
    dtype = torch.float64 if spec.dtype == "float64" else torch.float32
    x = torch.tensor(data.value("inputs"), dtype=dtype).reshape(data.shape("inputs"))
    y = torch.tensor(data.value("targets"), dtype=dtype).reshape(data.shape("targets"))
    activation = str(spec.smoke.get("activation", "relu"))

    class FrozenMLP(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.w1 = torch.nn.Parameter(torch.tensor(data.value("w1"), dtype=dtype).reshape(data.shape("w1")))
            self.b1 = torch.nn.Parameter(torch.tensor(data.value("b1"), dtype=dtype).reshape(data.shape("b1")))
            self.w2 = torch.nn.Parameter(torch.tensor(data.value("w2"), dtype=dtype).reshape(data.shape("w2")))
            self.b2 = torch.nn.Parameter(torch.tensor(data.value("b2"), dtype=dtype).reshape(data.shape("b2")))

        def forward(self, values):
            hidden = values.matmul(self.w1) + self.b1
            hidden = torch.relu(hidden) if activation == "relu" else torch.tanh(hidden)
            return hidden.matmul(self.w2) + self.b2

    model = FrozenMLP()
    adapter = build_pytorch_full_step(
        model, torch.nn.MSELoss(),
        learning_rate=float(spec.smoke["learning_rate"]),
        compile_step=compile_step, torch_module=torch,
    )
    losses: list[float] = []
    try:
        for _ in range(int(spec.smoke["steps"])):
            losses.append(float(adapter.step(x, y).detach().cpu()))
    except Exception as exc:
        if compile_step:
            raise BaselineUnavailable(f"full-step torch.compile execution unavailable: {exc}") from exc
        raise
    with torch.no_grad():
        final_prediction = torch.func.functional_call(
            model,
            (adapter.parameters, adapter.buffers),
            (x,),
        )
        final_loss = float(torch.mean((final_prediction - y) ** 2).detach().cpu())
    ordered = [final_loss]
    for name in ("w1", "b1", "w2", "b2"):
        ordered.extend(float(item) for item in adapter.parameters[name].detach().cpu().reshape(-1))
    label = "pytorch-compile-fullstep/1" if compile_step else "pytorch-eager-fullstep/1"
    return _passed(label, spec, data, tuple(ordered), {**asdict(adapter.metadata), "performance_measured": False})


def _pytorch_eager(spec: WorkloadSpec, data: GeneratedWorkload, _: bool) -> AdapterResult:
    return _pytorch(spec, data, False)


def _pytorch_compile(spec: WorkloadSpec, data: GeneratedWorkload, allow_toolchain: bool) -> AdapterResult:
    if not allow_toolchain:
        return _unavailable("pytorch-compile-fullstep/1", spec, data, "compiler execution requires explicit allow_toolchain=True")
    return _pytorch(spec, data, True)


def _native_c_no_t(spec: WorkloadSpec, data: GeneratedWorkload, allow_toolchain: bool) -> AdapterResult:
    if spec.family != "dense-mlp":
        return _unavailable("native-c-no-t/1", spec, data, "v1 independent C oracle supports dense MLP only")
    if not allow_toolchain:
        return _unavailable("native-c-no-t/1", spec, data, "native compilation requires explicit allow_toolchain=True")
    total_values = sum(len(items) for items in data.values.values())
    if total_values > 60_000:
        return _unavailable("native-c-no-t/1", spec, data, "bounded smoke source cap is 60000 scalars")
    try:
        from casulo.t.native import _compiler_version, _find_compiler
        compiler = _find_compiler()
    except Exception as exc:
        raise BaselineUnavailable(f"C compiler unavailable: {exc}") from exc
    source_text = _render_dense_c_smoke(spec, data)
    with tempfile.TemporaryDirectory(prefix="casulo-livelab-no-t-") as temporary:
        root = Path(temporary)
        source = root / "oracle.c"
        executable = root / ("oracle.exe" if os.name == "nt" else "oracle")
        source.write_text(source_text, encoding="ascii", newline="\n")
        name = compiler.name.lower()
        if name in {"cl", "cl.exe"}:
            command = [str(compiler), "/nologo", "/O2", "/fp:precise", str(source), f"/Fe:{executable}"]
        elif "gcc" in name or "clang" in name or name in {"cc", "cc.exe"}:
            command = [str(compiler), "-O2", "-std=c11", "-fno-fast-math", str(source), "-o", str(executable)]
        else:
            raise BaselineUnavailable(f"unsupported C compiler family: {compiler}")
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if compiled.returncode != 0 or not executable.is_file():
            raise BaselineUnavailable("independent C oracle failed to compile: " + (compiled.stderr or compiled.stdout)[-1000:])
        executed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10, check=False)
        if executed.returncode != 0:
            raise RuntimeError("independent C oracle failed: " + executed.stderr[-1000:])
        try:
            output = tuple(float(item) for item in executed.stdout.split())
        except ValueError as exc:
            raise RuntimeError("independent C oracle emitted invalid numeric output") from exc
    return _passed(
        "native-c-no-t/1", spec, data, output,
        {"compiler": str(compiler), "compiler_version": _compiler_version(compiler), "source_sha256": hashlib.sha256(source_text.encode("ascii")).hexdigest(), "generated_without_t": True},
    )


def _historical_t_c99(spec: WorkloadSpec, data: GeneratedWorkload, allow_toolchain: bool) -> AdapterResult:
    if spec.workload_id != "flood-surrogate-historical":
        return _unavailable("historical-t-c99/0.4", spec, data, "historical backend is only equivalent to FloodSurrogate 8x8x1 relu/mse/SGD")
    if not allow_toolchain:
        return _unavailable("historical-t-c99/0.4", spec, data, "GCC/Clang OpenMP build requires explicit allow_toolchain=True")
    try:
        import numpy as np
        from casulo.t.training import (
            TrainingDataset,
            _native_trainer,
            build_training_artifact,
            compile_training_artifact,
            parse_training_file,
        )
    except ImportError as exc:
        raise BaselineUnavailable(str(exc)) from exc
    source = Path(__file__).resolve().parents[3] / "examples" / "t" / "flood_surrogate_training.t"
    training_spec = replace(parse_training_file(source), epochs=int(spec.smoke["steps"]))
    inputs = np.asarray(data.value("inputs"), dtype=np.float64).reshape(data.shape("inputs"))
    targets = np.asarray(data.value("targets"), dtype=np.float64).reshape(-1)
    initial = np.concatenate(tuple(np.asarray(data.value(name), dtype=np.float64) for name in ("w1", "b1", "w2", "b2")))
    dataset = TrainingDataset(inputs, targets, inputs, targets, data.sha256, data.seed, tuple(f"x{index}" for index in range(8)))
    with tempfile.TemporaryDirectory(prefix="casulo-livelab-t-c99-") as temporary:
        artifact = build_training_artifact(source, Path(temporary) / "artifact")
        build = compile_training_artifact(artifact)
        outcome = _native_trainer(training_spec, dataset, initial, build, 1)()
    output = (float(outcome.final_loss), *(float(item) for item in outcome.parameters.reshape(-1)))
    return _passed("historical-t-c99/0.4", spec, data, output, {"compiler": build.compiler, "source_sha256": build.source_sha256, "performance_measured": False})


def _general_ir_tcap(spec: WorkloadSpec, data: GeneratedWorkload, allow_toolchain: bool) -> AdapterResult:
    if spec.workload_id != "flood-surrogate-historical":
        return _unavailable("t-general-ir-tcap/0.1", spec, data, "TCAP backend 0.1 supports FloodSurrogate 8x8x1 only")
    if not allow_toolchain:
        return _unavailable("t-general-ir-tcap/0.1", spec, data, "pinned Rust AOT build requires explicit allow_toolchain=True")
    from casulo.t.learn_canary import parse_flood_canary
    from casulo.t.learn_native import build_learn_tcap
    from casulo.t.tcap import load_tcap

    source = Path(__file__).resolve().parents[3] / "examples" / "t" / "flood_surrogate_training.t"
    with tempfile.TemporaryDirectory(prefix="casulo-livelab-tcap-") as temporary:
        artifact = build_learn_tcap(source, temporary)
        package = load_tcap(artifact.tcap_file)
        segment = next(item for item in package.segments if item.name == "canary")
        canary = parse_flood_canary(segment.data)
    # This canary has its own frozen data and 400-step scope. It is executable
    # correctness evidence but cannot be compared to the shared two-step smoke
    # fixture, so it is deliberately unavailable for the shared pair.
    return AdapterResult(
        "t-general-ir-tcap/0.1", spec.identity, AdapterStatus.UNAVAILABLE,
        spec.operation_expectations, data.sha256, None, 0,
        {"reason": "TCAP canary data/steps differ from shared smoke fixture", "artifact_sha256": artifact.artifact_sha256, "canary_final_loss": canary.expected_final_loss, "tcap_integrity": "PASS", "performance_measured": False},
    )


def _numpy_reference(spec: WorkloadSpec, data: GeneratedWorkload, np: Any) -> tuple[float, ...]:
    dtype = np.float64 if spec.dtype == "float64" else np.float32

    def array(name: str) -> Any:
        return np.asarray(data.value(name), dtype=dtype).reshape(data.shape(name))

    if spec.family == "dense-mlp":
        x, target = array("inputs"), array("targets")
        w1, b1, w2, b2 = array("w1").copy(), array("b1").copy(), array("w2").copy(), array("b2").copy()
        activation = str(spec.smoke.get("activation", "relu"))
        for _ in range(int(spec.smoke["steps"])):
            pre = x @ w1 + b1
            hidden = np.maximum(pre, 0) if activation == "relu" else np.tanh(pre)
            prediction = hidden @ w2 + b2
            error = prediction - target
            grad_prediction = (dtype(2.0) / dtype(error.size)) * error
            grad_w2 = hidden.T @ grad_prediction
            grad_b2 = grad_prediction.sum(axis=0)
            grad_hidden = grad_prediction @ w2.T
            grad_pre = grad_hidden * ((pre > 0) if activation == "relu" else (1 - hidden * hidden))
            grad_w1 = x.T @ grad_pre
            grad_b1 = grad_pre.sum(axis=0)
            lr = dtype(spec.smoke["learning_rate"])
            w1 -= lr * grad_w1
            b1 -= lr * grad_b1
            w2 -= lr * grad_w2
            b2 -= lr * grad_b2
        final_pre = x @ w1 + b1
        final_hidden = np.maximum(final_pre, 0) if activation == "relu" else np.tanh(final_pre)
        final_error = final_hidden @ w2 + b2 - target
        final_loss = np.mean(final_error * final_error)
        return (float(final_loss), *(float(item) for item in np.concatenate((w1.reshape(-1), b1, w2.reshape(-1), b2))))
    if spec.family == "convolution":
        x, kernel, bias = array("inputs"), array("kernel"), array("bias")
        batch, _, height, width = x.shape
        channels, _, kh, kw = kernel.shape
        output = np.empty((batch, channels, height - kh + 1, width - kw + 1), dtype=dtype)
        for n in range(batch):
            for channel in range(channels):
                for row in range(output.shape[2]):
                    for column in range(output.shape[3]):
                        output[n, channel, row, column] = np.sum(x[n, :, row:row + kh, column:column + kw] * kernel[channel]) + bias[channel]
        return tuple(float(item) for item in output.reshape(-1))
    if spec.family == "attention":
        x = array("inputs")
        q, k, v = x @ array("wq"), x @ array("wk"), x @ array("wv")
        scores = (q @ np.swapaxes(k, -1, -2)) / dtype(math.sqrt(q.shape[-1]))
        scores -= scores.max(axis=-1, keepdims=True)
        weights = np.exp(scores)
        weights /= weights.sum(axis=-1, keepdims=True)
        return tuple(float(item) for item in ((weights @ v) @ array("wo")).reshape(-1))
    if spec.family == "dynamic-control":
        x = array("inputs")
        result = np.stack([x[index, :length].sum(axis=0) / dtype(length) for index, length in enumerate(data.lengths)])
        return tuple(float(item) for item in result.reshape(-1))
    if spec.family == "unfavorable":
        x = array("inputs")
        output = []
        for row in x:
            state = dtype(0.0)
            for item in row:
                state = state * dtype(0.875) + (item * item if item > state else -item * dtype(0.5))
            output.append(float(state))
        return tuple(output)
    if spec.family == "scheduler-interference":
        flow, residual = array("flow"), array("residual")
        flow_output = flow.sum(axis=1)
        residual_output = (residual * residual).sum(axis=1)
        return tuple(float(item) for item in np.concatenate((flow_output, residual_output)))
    raise BaselineUnavailable(f"NumPy semantic reference does not support {spec.family}")


def _render_dense_c_smoke(spec: WorkloadSpec, data: GeneratedWorkload) -> str:
    batch, inputs = data.shape("inputs")
    _, outputs = data.shape("targets")
    hidden = data.shape("b1")[0]
    real = "double" if spec.dtype == "float64" else "float"
    suffix = "" if real == "double" else "f"
    printf = "%.17g" if real == "double" else "%.9g"

    def literal(value: float) -> str:
        rendered = format(value, ".17g" if real == "double" else ".9g")
        if "e" not in rendered and "." not in rendered:
            rendered += ".0"
        return rendered + suffix

    def declaration(name: str) -> str:
        values = ",".join(literal(item) for item in data.value(name))
        return f"static {real} {name}[] = {{{values}}};"

    activation = str(spec.smoke.get("activation", "relu"))
    activate = "v > 0 ? v : 0" if activation == "relu" else "tanh(v)"
    derivative = "pre[n*H+h] > 0 ? 1 : 0" if activation == "relu" else "1 - hidden[n*H+h]*hidden[n*H+h]"
    return f"""#include <math.h>
#include <stdio.h>
#define N {batch}
#define F {inputs}
#define H {hidden}
#define O {outputs}
#define STEPS {int(spec.smoke['steps'])}
{declaration('inputs')}
{declaration('targets')}
{declaration('w1')}
{declaration('b1')}
{declaration('w2')}
{declaration('b2')}
static {real} pre[N*H], hidden[N*H], prediction[N*O], grad_prediction[N*O];
static {real} gw1[F*H], gb1[H], gw2[H*O], gb2[O];
int main(void) {{
  {real} loss = 0, lr = ({real}){literal(float(spec.smoke['learning_rate']))};
  for (int step=0; step<STEPS; ++step) {{
    for (int n=0;n<N;++n) for(int h=0;h<H;++h) {{
      {real} v=b1[h]; for(int f=0;f<F;++f) v += inputs[n*F+f]*w1[f*H+h];
      pre[n*H+h]=v; hidden[n*H+h]={activate};
    }}
    loss=0;
    for(int n=0;n<N;++n) for(int o=0;o<O;++o) {{
      {real} v=b2[o]; for(int h=0;h<H;++h) v += hidden[n*H+h]*w2[h*O+o];
      prediction[n*O+o]=v; {real} e=v-targets[n*O+o]; loss += e*e;
      grad_prediction[n*O+o]=(({real})2/(({real})N*O))*e;
    }}
    loss /= ({real})(N*O);
    for(int i=0;i<F*H;++i) gw1[i]=0; for(int i=0;i<H;++i) gb1[i]=0;
    for(int i=0;i<H*O;++i) gw2[i]=0; for(int i=0;i<O;++i) gb2[i]=0;
    for(int n=0;n<N;++n) for(int o=0;o<O;++o) {{
      {real} g=grad_prediction[n*O+o]; gb2[o]+=g;
      for(int h=0;h<H;++h) gw2[h*O+o]+=hidden[n*H+h]*g;
    }}
    for(int n=0;n<N;++n) for(int h=0;h<H;++h) {{
      {real} gh=0; for(int o=0;o<O;++o) gh += grad_prediction[n*O+o]*w2[h*O+o];
      {real} gp=gh*({derivative}); gb1[h]+=gp;
      for(int f=0;f<F;++f) gw1[f*H+h]+=inputs[n*F+f]*gp;
    }}
    for(int i=0;i<F*H;++i) w1[i]-=lr*gw1[i]; for(int i=0;i<H;++i) b1[i]-=lr*gb1[i];
    for(int i=0;i<H*O;++i) w2[i]-=lr*gw2[i]; for(int i=0;i<O;++i) b2[i]-=lr*gb2[i];
  }}
  loss=0;
  for (int n=0;n<N;++n) for(int o=0;o<O;++o) {{
    {real} out=b2[o];
    for(int h=0;h<H;++h) {{ {real} v=b1[h]; for(int f=0;f<F;++f) v += inputs[n*F+f]*w1[f*H+h]; out += ({activate})*w2[h*O+o]; }}
    {real} e=out-targets[n*O+o]; loss += e*e;
  }}
  loss /= ({real})(N*O);
  printf("{printf} ", ({real})loss);
  for(int i=0;i<F*H;++i) printf("{printf} ", w1[i]); for(int i=0;i<H;++i) printf("{printf} ", b1[i]);
  for(int i=0;i<H*O;++i) printf("{printf} ", w2[i]); for(int i=0;i<O;++i) printf("{printf} ", b2[i]);
  return 0;
}}
"""


def _digest(values: tuple[float, ...]) -> str:
    return hashlib.sha256(json.dumps(values, allow_nan=False, separators=(",", ":")).encode("ascii")).hexdigest()


def _passed(adapter: str, spec: WorkloadSpec, data: GeneratedWorkload, output: tuple[float, ...], details: dict[str, Any]) -> AdapterResult:
    if not output or any(not math.isfinite(item) for item in output):
        raise ValueError("adapter emitted empty or non-finite output")
    return AdapterResult(adapter, spec.identity, AdapterStatus.PASS, spec.operation_expectations, data.sha256, _digest(output), len(output), {**details, "performance_measured": False, "profile": "bounded-smoke"}, output)


def _unavailable(adapter: str, spec: WorkloadSpec, data: GeneratedWorkload, reason: str) -> AdapterResult:
    return AdapterResult(adapter, spec.identity, AdapterStatus.UNAVAILABLE, spec.operation_expectations, data.sha256, None, 0, {"reason": reason, "performance_measured": False})


_ADAPTERS: dict[str, Adapter] = {
    "numpy-semantic": _numpy_semantic,
    "numpy-blas": _numpy_blas,
    "pytorch-eager": _pytorch_eager,
    "pytorch-compile": _pytorch_compile,
    "native-c-no-t": _native_c_no_t,
    "historical-t-c99": _historical_t_c99,
    "t-general-ir-tcap": _general_ir_tcap,
}
