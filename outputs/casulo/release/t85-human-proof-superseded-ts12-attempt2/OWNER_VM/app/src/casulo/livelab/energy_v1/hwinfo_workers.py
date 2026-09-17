from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from casulo.t.learn_canary import LearnCanary, parse_flood_canary
from casulo.t.tcap import load_tcap

from .schemas import canonical_bytes, sha256_bytes


WORKER_PROTOCOL = "casulo-hwinfo-persistent-worker/1.0"
TCAP_IMPLEMENTATION = "t-general-ir-tcap/0.1"
EAGER_IMPLEMENTATION = "pytorch-eager-fullstep/1"
SCIENTIFIC_TRAINING_RECORDS = 1_024


def load_workload(tcap_path: Path) -> tuple[bytes, bytes, LearnCanary]:
    package = load_tcap(Path(tcap_path))
    segments = {item.name: item.data for item in package.segments}
    code = segments["code"]
    canary_raw = segments["canary"]
    return code, canary_raw, parse_flood_canary(canary_raw)


def validate_scientific_training_unit(tcap_path: Path) -> LearnCanary:
    """Fail closed when a correctness canary is offered as an energy unit."""

    _, _, canary = load_workload(tcap_path)
    if canary.records != SCIENTIFIC_TRAINING_RECORDS:
        raise ValueError(
            "scientific energy campaign requires a 1,024-record full training work unit; "
            f"TCAP contains the {canary.records}-record bounded correctness canary"
        )
    return canary


def build_native_worker(tcap_path: Path, output_directory: Path) -> dict[str, Any]:
    code, canary_raw, canary = load_workload(tcap_path)
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = output / "tcap_hwinfo_worker.rs"
    executable = output / "tcap_hwinfo_worker.exe"
    source.write_text(_render_native_worker(code, canary), encoding="utf-8", newline="\n")
    rustc = _rustc()
    started = time.monotonic()
    result = subprocess.run(
        [str(rustc), str(source), "--edition=2021", "-C", "opt-level=3", "-C", "target-cpu=native", "-o", str(executable)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0 or not executable.is_file():
        raise RuntimeError("native TCAP worker compilation failed: " + (result.stderr or result.stdout).strip())
    return {
        "protocol": WORKER_PROTOCOL,
        "implementation": TCAP_IMPLEMENTATION,
        "executable": str(executable),
        "executable_sha256": _sha256_file(executable),
        "source": str(source),
        "source_sha256": _sha256_file(source),
        "tcap": str(Path(tcap_path).resolve()),
        "tcap_sha256": _sha256_file(Path(tcap_path)),
        "dataset_sha256": hashlib.sha256(canary_raw).hexdigest(),
        "epochs": canary.epochs,
        "precision": "float64",
        "compilation_seconds": time.monotonic() - started,
        "compiler": subprocess.run([str(rustc), "--version", "--verbose"], capture_output=True, text=True, check=True).stdout.strip(),
    }


def eager_worker_main(tcap_path: Path, *, threads: int = 1) -> int:
    if threads < 1:
        raise ValueError("threads must be positive")
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(threads))
    import torch

    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    torch.set_default_dtype(torch.float64)
    _, canary_raw, canary = load_workload(tcap_path)
    x = torch.tensor(canary.inputs, dtype=torch.float64).reshape(canary.records, canary.input_features)
    y = torch.tensor(canary.targets, dtype=torch.float64).reshape(canary.records)
    initial = tuple(canary.initial_parameters)
    f, h = canary.input_features, canary.hidden_features
    p0, p1, p2 = f * h, f * h + h, f * h + h + h

    def one_unit() -> tuple[float, float, tuple[float, ...]]:
        values = {
            "w1": torch.tensor(initial[:p0]).reshape(f, h).clone().requires_grad_(True),
            "b1": torch.tensor(initial[p0:p1]).clone().requires_grad_(True),
            "w2": torch.tensor(initial[p1:p2]).clone().requires_grad_(True),
            "b2": torch.tensor([initial[p2]]).clone().requires_grad_(True),
        }

        def loss_of(current):
            prediction = torch.relu(x @ current["w1"] + current["b1"]) @ current["w2"] + current["b2"][0]
            return torch.mean((prediction - y) ** 2)

        initial_loss = float(loss_of(values).detach())
        for _ in range(canary.epochs):
            loss = loss_of(values)
            gradients = torch.autograd.grad(loss, tuple(values.values()), create_graph=False)
            values = {
                name: value - canary.learning_rate * gradient
                for (name, value), gradient in zip(values.items(), gradients, strict=True)
            }
        final_loss = float(loss_of(values).detach())
        ordered = (
            *values["w1"].detach().reshape(-1).tolist(),
            *values["b1"].detach().tolist(),
            *values["w2"].detach().tolist(),
            *values["b2"].detach().tolist(),
        )
        return initial_loss, final_loss, tuple(float(item) for item in ordered)

    print(json.dumps({
        "protocol": WORKER_PROTOCOL,
        "event": "READY",
        "implementation": EAGER_IMPLEMENTATION,
        "pid": os.getpid(),
        "threads": torch.get_num_threads(),
        "dataset_sha256": hashlib.sha256(canary_raw).hexdigest(),
        "epochs": canary.epochs,
        "precision": "float64",
    }, separators=(",", ":")), flush=True)
    for raw in sys.stdin:
        command = raw.strip().split()
        if not command:
            continue
        if command[0] == "STOP":
            return 0
        if command[0] != "RUN" or len(command) != 2:
            print(json.dumps({"event": "ERROR", "reason": "invalid_command"}), flush=True)
            continue
        count = int(command[1])
        started = time.monotonic_ns()
        result = None
        for _ in range(count):
            result = one_unit()
        elapsed = (time.monotonic_ns() - started) / 1e9
        assert result is not None
        print(json.dumps(_unit_result(EAGER_IMPLEMENTATION, canary_raw, canary, result, count, elapsed), separators=(",", ":"), allow_nan=False), flush=True)
    return 0


def _unit_result(
    implementation: str,
    canary_raw: bytes,
    canary: LearnCanary,
    result: tuple[float, float, tuple[float, ...]],
    count: int,
    elapsed: float,
) -> dict[str, Any]:
    initial_loss, final_loss, parameters = result
    predictions = _predictions(canary, parameters)
    numeric = [initial_loss, final_loss, *parameters, *predictions]
    maximum = max(abs(left - right) for left, right in zip(parameters, canary.expected_final_parameters, strict=True))
    passed = (
        abs(initial_loss - canary.expected_initial_loss) <= canary.tolerance
        and abs(final_loss - canary.expected_final_loss) <= canary.tolerance
        and maximum <= canary.tolerance
    )
    return {
        "protocol": WORKER_PROTOCOL,
        "event": "RESULT",
        "status": "PASS" if passed else "FAIL",
        "implementation": implementation,
        "K": count,
        "epochs_per_training": canary.epochs,
        "fresh_mathematical_state_per_training": True,
        "dataset_sha256": hashlib.sha256(canary_raw).hexdigest(),
        "loss": {"initial": initial_loss, "final": final_loss},
        "parameters": list(parameters),
        "predictions": list(predictions),
        "numeric_output_sha256": sha256_bytes(canonical_bytes(numeric)),
        "max_abs_parameter_error_vs_frozen_oracle": maximum,
        "elapsed_seconds": elapsed,
        "seconds_per_training": elapsed / count,
    }


def _predictions(canary: LearnCanary, parameters: tuple[float, ...]) -> tuple[float, ...]:
    f, h = canary.input_features, canary.hidden_features
    p0, p1, p2 = f * h, f * h + h, f * h + h + h
    w1, b1, w2, b2 = parameters[:p0], parameters[p0:p1], parameters[p1:p2], parameters[p2]
    result = []
    for record in range(canary.records):
        hidden = [
            max(0.0, b1[unit] + sum(canary.inputs[record * f + feature] * w1[feature * h + unit] for feature in range(f)))
            for unit in range(h)
        ]
        result.append(b2 + sum(hidden[unit] * w2[unit] for unit in range(h)))
    return tuple(result)


def _render_native_worker(code: bytes, canary: LearnCanary) -> str:
    def byte_array(values: bytes) -> str:
        return ",".join(str(value) for value in values)

    def bits_array(values: tuple[float, ...]) -> str:
        return ",".join(f"f64::from_bits(0x{_float_bits(value):016x})" for value in values)

    return f'''use std::ffi::c_void;
use std::io::{{self, BufRead, Write}};
use std::ptr::copy_nonoverlapping;
use std::time::Instant;

#[repr(C)]
struct LearnContext {{
    inputs: *const f64, targets: *const f64, parameters: *mut f64,
    gradients: *mut f64, records: usize, epochs: usize, learning_rate: f64,
    initial_loss: *mut f64, final_loss: *mut f64,
}}

#[link(name = "kernel32")]
extern "system" {{
    fn VirtualAlloc(address: *mut c_void, size: usize, allocation: u32, protect: u32) -> *mut c_void;
    fn VirtualProtect(address: *mut c_void, size: usize, protect: u32, old: *mut u32) -> i32;
    fn VirtualFree(address: *mut c_void, size: usize, free_type: u32) -> i32;
}}
type Entry = unsafe extern "sysv64" fn(*mut LearnContext) -> i32;

fn emit_result(k: usize, elapsed: f64, initial_loss: f64, final_loss: f64, parameters: &[f64], maximum: f64) {{
    print!("{{}}", r#"{{"protocol":"{WORKER_PROTOCOL}","event":"RESULT","status":"PASS","implementation":"{TCAP_IMPLEMENTATION}","K":"#);
    print!("{{}}", k);
    print!("{{}}", r#","epochs_per_training":{canary.epochs},"fresh_mathematical_state_per_training":true,"loss":{{"initial":"#);
    print!("{{:.17e}}", initial_loss);
    print!("{{}}", r#","final":"#);
    print!("{{:.17e}}", final_loss);
    print!("{{}}", r#"}},"parameters":["#);
    for (index, value) in parameters.iter().enumerate() {{ if index > 0 {{ print!(","); }} print!("{{:.17e}}", value); }}
    print!("{{}}", r#"],"max_abs_parameter_error_vs_frozen_oracle":"#);
    print!("{{:.17e}}", maximum);
    print!("{{}}", r#", "elapsed_seconds":"#);
    print!("{{:.17e}}", elapsed);
    print!("{{}}", r#", "seconds_per_training":"#);
    print!("{{:.17e}}", elapsed / k as f64);
    println!("{{}}", "}}");
    io::stdout().flush().unwrap();
}}

fn main() {{
    let code = [{byte_array(code)}u8];
    let inputs = [{bits_array(canary.inputs)}];
    let targets = [{bits_array(canary.targets)}];
    let initial_parameters = [{bits_array(canary.initial_parameters)}];
    let expected = [{bits_array(canary.expected_final_parameters)}];
    unsafe {{
        let memory = VirtualAlloc(std::ptr::null_mut(), code.len(), 0x3000, 0x04);
        if memory.is_null() {{ std::process::exit(10); }}
        copy_nonoverlapping(code.as_ptr(), memory.cast::<u8>(), code.len());
        let mut old = 0u32;
        if VirtualProtect(memory, code.len(), 0x20, &mut old) == 0 {{ std::process::exit(11); }}
        let entry: Entry = std::mem::transmute(memory);
        print!("{{}}", r#"{{"protocol":"{WORKER_PROTOCOL}","event":"READY","implementation":"{TCAP_IMPLEMENTATION}","pid":"#);
        print!("{{}}", std::process::id());
        println!("{{}}", r#","threads":1,"epochs":{canary.epochs},"precision":"float64"}}"#);
        io::stdout().flush().unwrap();
        for line in io::stdin().lock().lines() {{
            let line = line.unwrap();
            if line.trim() == "STOP" {{ break; }}
            let fields: Vec<&str> = line.split_whitespace().collect();
            if fields.len() != 2 || fields[0] != "RUN" {{ std::process::exit(12); }}
            let k: usize = fields[1].parse().unwrap();
            if k == 0 {{ std::process::exit(13); }}
            let started = Instant::now();
            let mut last_parameters = initial_parameters;
            let mut last_initial = 0.0f64;
            let mut last_final = 0.0f64;
            for _ in 0..k {{
                let mut parameters = initial_parameters;
                let mut gradients = [0.0f64; {canary.parameter_count}];
                let mut initial_loss = 0.0f64;
                let mut final_loss = 0.0f64;
                let mut context = LearnContext {{
                    inputs: inputs.as_ptr(), targets: targets.as_ptr(), parameters: parameters.as_mut_ptr(),
                    gradients: gradients.as_mut_ptr(), records: {canary.records}, epochs: {canary.epochs},
                    learning_rate: f64::from_bits(0x{_float_bits(canary.learning_rate):016x}),
                    initial_loss: &mut initial_loss, final_loss: &mut final_loss,
                }};
                if entry(&mut context) != 0 {{ std::process::exit(14); }}
                last_parameters = parameters; last_initial = initial_loss; last_final = final_loss;
            }}
            let elapsed = started.elapsed().as_secs_f64();
            let mut maximum = 0.0f64;
            for index in 0..last_parameters.len() {{ maximum = maximum.max((last_parameters[index] - expected[index]).abs()); }}
            if (last_initial - f64::from_bits(0x{_float_bits(canary.expected_initial_loss):016x})).abs() > {canary.tolerance!r}
                || (last_final - f64::from_bits(0x{_float_bits(canary.expected_final_loss):016x})).abs() > {canary.tolerance!r}
                || maximum > {canary.tolerance!r} {{ std::process::exit(15); }}
            emit_result(k, elapsed, last_initial, last_final, &last_parameters, maximum);
        }}
        if VirtualFree(memory, 0, 0x8000) == 0 {{ std::process::exit(16); }}
    }}
}}
'''


def _float_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def _rustc() -> Path:
    candidates = [Path.home() / ".cargo" / "bin" / "rustc.exe"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("rustc was not found")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--eager-worker", action="store_true")
    parser.add_argument("--tcap", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=1)
    options = parser.parse_args()
    if not options.eager_worker:
        raise SystemExit("only --eager-worker is valid for the Python worker")
    raise SystemExit(eager_worker_main(options.tcap, threads=options.threads))
