from __future__ import annotations

import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casulo.t.full_work_unit import (
    CASE_HEADER,
    DATASET_HEADER,
    DATASET_MAGIC,
    EPOCHS,
    FULL_WORK_UNIT_SCHEMA,
    HIDDEN_FEATURES,
    INITIALIZATION_HEADER,
    INITIALIZATION_MAGIC,
    INPUT_FEATURES,
    OUTPUT_FEATURES,
    PARAMETER_COUNT,
    RECORDS,
    SCIENTIFIC_WORK_UNIT,
    WorkUnitContract,
    load_full_work_unit_tcap,
    sha256_bytes,
)


TCAP_FULL_IMPLEMENTATION = "t-general-ir-tcap-full/1.0"
EAGER_FULL_IMPLEMENTATION = "pytorch-eager-fullstep/2.0"
RESULT_MAGIC = b"FWRES1\0\0"
RESULT_HEADER = struct.Struct("<8sII")
RESULT_CASE_HEADER = struct.Struct("<IIQ32s6Qdd")
RECEIPT_SCHEMA = "casulo-work-receipt/1.0"
TOLERANCE = 1e-9
AFFINITY_CPU = 4


@dataclass(frozen=True, slots=True)
class CaseInput:
    index: int
    case_id: int
    seed: int
    nonce: bytes
    parameters: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CaseResult:
    index: int
    case_id: int
    seed: int
    nonce: bytes
    epochs_completed: int
    forward_epochs: int
    backward_epochs: int
    optimizer_steps: int
    records_visited: int
    parameter_writes: int
    initial_loss: float
    final_loss: float
    parameters: tuple[float, ...]
    predictions: tuple[float, ...]


def _read_u32(raw: bytes, offset: int) -> int:
    return struct.unpack_from("<I", raw, offset)[0]


def parse_dataset(raw: bytes) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if len(raw) < DATASET_HEADER.size:
        raise ValueError("scientific dataset is truncated")
    magic, records, inputs, targets, bits = DATASET_HEADER.unpack_from(raw)
    if (magic, records, inputs, targets, bits) != (
        DATASET_MAGIC,
        RECORDS,
        INPUT_FEATURES,
        OUTPUT_FEATURES,
        64,
    ):
        raise ValueError("scientific dataset header is invalid")
    scalar_count = RECORDS * INPUT_FEATURES + RECORDS
    if len(raw) != DATASET_HEADER.size + scalar_count * 8:
        raise ValueError("scientific dataset length is invalid")
    values = struct.unpack_from(f"<{scalar_count}d", raw, DATASET_HEADER.size)
    return tuple(values[: RECORDS * INPUT_FEATURES]), tuple(values[RECORDS * INPUT_FEATURES :])


def parse_initializations(raw: bytes) -> tuple[CaseInput, ...]:
    if len(raw) < INITIALIZATION_HEADER.size:
        raise ValueError("initialization bundle is truncated")
    magic, case_count, parameters, bits, _bundle_nonce = INITIALIZATION_HEADER.unpack_from(raw)
    if magic != INITIALIZATION_MAGIC or parameters != PARAMETER_COUNT or bits != 64:
        raise ValueError("initialization bundle header is invalid")
    stride = CASE_HEADER.size + PARAMETER_COUNT * 8
    if len(raw) != INITIALIZATION_HEADER.size + case_count * stride:
        raise ValueError("initialization bundle length is invalid")
    result = []
    offset = INITIALIZATION_HEADER.size
    for index in range(case_count):
        case_id, seed, nonce = CASE_HEADER.unpack_from(raw, offset)
        offset += CASE_HEADER.size
        values = struct.unpack_from(f"<{PARAMETER_COUNT}d", raw, offset)
        offset += PARAMETER_COUNT * 8
        result.append(CaseInput(index, case_id, seed, nonce, tuple(values)))
    if len({item.nonce for item in result}) != case_count:
        raise ValueError("initialization nonces are not unique")
    if len({sha256_bytes(struct.pack(f'<{PARAMETER_COUNT}d', *item.parameters)) for item in result}) != case_count:
        raise ValueError("initial parameters are not unique")
    return tuple(result)


def validate_full_tcap(path: Path) -> tuple[WorkUnitContract, dict[str, bytes], tuple[CaseInput, ...]]:
    contract, segments = load_full_work_unit_tcap(path)
    parse_dataset(segments["scientific_dataset"])
    cases = parse_initializations(segments["initialization_bundle"])
    if contract.workload_class != SCIENTIFIC_WORK_UNIT or not contract.scientific_eligible:
        raise ValueError("TCAP is not scientifically eligible")
    if contract.work_unit_schema != FULL_WORK_UNIT_SCHEMA:
        raise ValueError("TCAP work-unit schema mismatch")
    return contract, segments, cases


def build_full_native_worker(tcap_path: Path, output_directory: Path) -> dict[str, Any]:
    contract, segments, cases = validate_full_tcap(tcap_path)
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = output / "tcap_full_worker.rs"
    executable = output / "tcap_full_worker.exe"
    source.write_text(_render_native_worker(segments["code"]), encoding="utf-8", newline="\n")
    rustc = Path.home() / ".cargo/bin/rustc.exe"
    if not rustc.is_file():
        raise RuntimeError("rustc is unavailable")
    started = time.perf_counter()
    process = subprocess.run(
        [
            str(rustc),
            str(source),
            "--edition=2021",
            "-C",
            "opt-level=3",
            "-C",
            "target-cpu=native",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if process.returncode != 0 or not executable.is_file():
        raise RuntimeError("full TCAP worker compilation failed: " + (process.stderr or process.stdout))
    return {
        "implementation": TCAP_FULL_IMPLEMENTATION,
        "executable": str(executable),
        "executable_sha256": _sha256_file(executable),
        "source": str(source),
        "source_sha256": _sha256_file(source),
        "tcap": str(Path(tcap_path).resolve()),
        "tcap_sha256": _sha256_file(tcap_path),
        "contract": contract.to_dict(),
        "case_count": len(cases),
        "compilation_seconds": time.perf_counter() - started,
    }


def run_eager_worker(
    tcap_path: Path,
    start: int,
    count: int,
    output_path: Path,
    *,
    threads: int = 1,
    marker_path: Path | None = None,
) -> dict[str, Any]:
    if threads != 1:
        raise ValueError("full Eager oracle is frozen to one thread")
    _pin_current_thread(AFFINITY_CPU)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    import torch

    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    torch.set_default_dtype(torch.float64)
    contract, segments, cases = validate_full_tcap(tcap_path)
    if start < 0 or count < 1 or start + count > len(cases):
        raise ValueError("requested case range is invalid")
    inputs, targets = parse_dataset(segments["scientific_dataset"])
    x = torch.tensor(inputs, dtype=torch.float64).reshape(RECORDS, INPUT_FEATURES)
    y = torch.tensor(targets, dtype=torch.float64)
    output = bytearray(RESULT_HEADER.pack(RESULT_MAGIC, count, RECORDS))
    start_unix_ns = time.time_ns()
    qpc_start, qpc_frequency = _qpc()
    cycle_start = _thread_cycles()
    monotonic_start = time.perf_counter_ns()
    for case in cases[start : start + count]:
        p0 = INPUT_FEATURES * HIDDEN_FEATURES
        p1 = p0 + HIDDEN_FEATURES
        p2 = p1 + HIDDEN_FEATURES
        w1 = torch.tensor(case.parameters[:p0]).reshape(INPUT_FEATURES, HIDDEN_FEATURES).clone().requires_grad_(True)
        b1 = torch.tensor(case.parameters[p0:p1]).clone().requires_grad_(True)
        w2 = torch.tensor(case.parameters[p1:p2]).clone().requires_grad_(True)
        b2 = torch.tensor(case.parameters[p2]).clone().requires_grad_(True)
        parameters = (w1, b1, w2, b2)
        optimizer = torch.optim.SGD(parameters, lr=contract.learning_rate)

        def forward():
            return torch.relu(x.matmul(w1) + b1).matmul(w2) + b2

        with torch.no_grad():
            initial_loss = float(torch.mean((forward() - y) ** 2))
        epochs = forward_epochs = backward_epochs = optimizer_steps = records_visited = parameter_writes = 0
        for _ in range(EPOCHS):
            optimizer.zero_grad(set_to_none=True)
            prediction = forward()
            forward_epochs += 1
            records_visited += RECORDS
            loss = torch.mean((prediction - y) ** 2)
            loss.backward()
            backward_epochs += 1
            optimizer.step()
            optimizer_steps += 1
            parameter_writes += PARAMETER_COUNT
            epochs += 1
        with torch.no_grad():
            prediction = forward()
            final_loss = float(torch.mean((prediction - y) ** 2))
            final_parameters = torch.cat((w1.reshape(-1), b1, w2, b2.reshape(1))).numpy().copy()
            final_predictions = prediction.numpy().copy()
        output.extend(
            RESULT_CASE_HEADER.pack(
                case.index,
                case.case_id,
                case.seed,
                case.nonce,
                epochs,
                forward_epochs,
                backward_epochs,
                optimizer_steps,
                records_visited,
                parameter_writes,
                initial_loss,
                final_loss,
            )
        )
        output.extend(final_parameters.astype("<f8", copy=False).tobytes())
        output.extend(final_predictions.astype("<f8", copy=False).tobytes())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        stream.write(output)
        stream.flush()
        os.fsync(stream.fileno())
    monotonic_ns = time.perf_counter_ns() - monotonic_start
    cycle_end = _thread_cycles()
    qpc_end, _ = _qpc()
    end_unix_ns = time.time_ns()
    if marker_path is not None:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            f"START {start_unix_ns}\nEND {end_unix_ns}\n",
            encoding="ascii",
            newline="\n",
        )
    return {
        "implementation": EAGER_FULL_IMPLEMENTATION,
        "start": start,
        "K": count,
        "worker_monotonic_ns": monotonic_ns,
        "qpc_ticks": qpc_end - qpc_start,
        "qpc_frequency": qpc_frequency,
        "thread_cycles": cycle_end - cycle_start,
        "start_unix_ns": start_unix_ns,
        "end_unix_ns": end_unix_ns,
        "result_file": str(output_path.resolve()),
        "result_sha256": _sha256_file(output_path),
    }


def parse_result_file(path: Path) -> tuple[CaseResult, ...]:
    raw = Path(path).read_bytes()
    if len(raw) < RESULT_HEADER.size:
        raise ValueError("full-worker result is truncated")
    magic, count, records = RESULT_HEADER.unpack_from(raw)
    if magic != RESULT_MAGIC or records != RECORDS:
        raise ValueError("full-worker result header is invalid")
    stride = RESULT_CASE_HEADER.size + (PARAMETER_COUNT + RECORDS) * 8
    if len(raw) != RESULT_HEADER.size + count * stride:
        raise ValueError("full-worker result length is invalid")
    result = []
    offset = RESULT_HEADER.size
    for _ in range(count):
        values = RESULT_CASE_HEADER.unpack_from(raw, offset)
        offset += RESULT_CASE_HEADER.size
        numeric = struct.unpack_from(f"<{PARAMETER_COUNT + RECORDS}d", raw, offset)
        offset += (PARAMETER_COUNT + RECORDS) * 8
        result.append(
            CaseResult(
                *values,
                tuple(numeric[:PARAMETER_COUNT]),
                tuple(numeric[PARAMETER_COUNT:]),
            )
        )
    return tuple(result)


def create_receipts(
    *,
    contract: WorkUnitContract,
    cases: tuple[CaseInput, ...],
    results: tuple[CaseResult, ...],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_index = {item.index: item for item in cases}
    receipts = []
    previous = bytes(32)
    for result in results:
        case = by_index[result.index]
        initial_raw = struct.pack(f"<{PARAMETER_COUNT}d", *case.parameters)
        parameter_raw = struct.pack(f"<{PARAMETER_COUNT}d", *result.parameters)
        prediction_raw = struct.pack(f"<{RECORDS}d", *result.predictions)
        counter_document = {
            "epochs_completed": result.epochs_completed,
            "forward_epochs": result.forward_epochs,
            "backward_epochs": result.backward_epochs,
            "optimizer_steps": result.optimizer_steps,
            "records_visited": result.records_visited,
            "parameter_writes": result.parameter_writes,
        }
        semantic_parameters = _semantic_hash(result.parameters)
        semantic_predictions = _semantic_hash(result.predictions)
        core = {
            "schema": RECEIPT_SCHEMA,
            "work_unit_id": contract.work_unit_schema,
            "case_id": f"case-{result.case_id:04d}",
            "nonce": result.nonce.hex(),
            "seed": result.seed,
            "dataset_hash": contract.dataset_hash,
            "initial_parameters_hash": sha256_bytes(initial_raw),
            **counter_document,
            "final_loss_quantized": round(result.final_loss / TOLERANCE),
            "final_parameters_hash": semantic_parameters,
            "predictions_hash": semantic_predictions,
            "runtime_counter_hash": sha256_bytes(_canonical(counter_document)),
        }
        receipt_hash = sha256_bytes(_canonical(core))
        chain_hash = hashlib.sha256(previous + bytes.fromhex(receipt_hash)).hexdigest()
        receipt = {
            **core,
            "raw_final_loss": result.final_loss,
            "raw_final_parameters_hash": sha256_bytes(parameter_raw),
            "raw_predictions_hash": sha256_bytes(prediction_raw),
            "receipt_hash": receipt_hash,
            "previous_chain_hash": previous.hex(),
            "chain_hash": chain_hash,
        }
        receipts.append(receipt)
        previous = bytes.fromhex(chain_hash)
    return receipts, {
        "schema": "casulo-work-receipt-chain/1.0",
        "receipts": len(receipts),
        "aggregate_hash": previous.hex(),
        "case_ids": [item["case_id"] for item in receipts],
    }


def validate_receipts(receipts: list[dict[str, Any]], expected: int) -> None:
    if len(receipts) != expected:
        raise ValueError("receipt count differs from K")
    for receipt in receipts:
        expected_values = {
            "epochs_completed": EPOCHS,
            "forward_epochs": EPOCHS,
            "backward_epochs": EPOCHS,
            "optimizer_steps": EPOCHS,
            "records_visited": RECORDS * EPOCHS,
            "parameter_writes": PARAMETER_COUNT * EPOCHS,
        }
        for name, value in expected_values.items():
            if receipt.get(name) != value:
                raise ValueError(f"receipt counter mismatch: {name}")
        if not receipt.get("receipt_hash") or not receipt.get("chain_hash"):
            raise ValueError("receipt is incomplete")


def compare_results(
    tcap: tuple[CaseResult, ...], eager: tuple[CaseResult, ...], tolerance: float = TOLERANCE
) -> dict[str, Any]:
    if len(tcap) != len(eager) or [x.case_id for x in tcap] != [x.case_id for x in eager]:
        raise ValueError("TCAP and Eager case sequences differ")
    per_case = []
    maximum_parameter = maximum_prediction = maximum_loss = 0.0
    for left, right in zip(tcap, eager, strict=True):
        parameter = max(abs(a - b) for a, b in zip(left.parameters, right.parameters, strict=True))
        prediction = max(abs(a - b) for a, b in zip(left.predictions, right.predictions, strict=True))
        loss = abs(left.final_loss - right.final_loss)
        counters_equal = left.epochs_completed == right.epochs_completed == EPOCHS and left.records_visited == right.records_visited == RECORDS * EPOCHS and left.optimizer_steps == right.optimizer_steps == EPOCHS
        passed = parameter <= tolerance and prediction <= tolerance and loss <= tolerance and counters_equal
        per_case.append({"case_id": left.case_id, "parameter_max_abs": parameter, "prediction_max_abs": prediction, "loss_abs": loss, "counters_equal": counters_equal, "passed": passed})
        maximum_parameter = max(maximum_parameter, parameter)
        maximum_prediction = max(maximum_prediction, prediction)
        maximum_loss = max(maximum_loss, loss)
    return {
        "status": "PASS" if all(item["passed"] for item in per_case) else "FAIL",
        "tolerance": tolerance,
        "maximum_parameter_abs_difference": maximum_parameter,
        "maximum_prediction_abs_difference": maximum_prediction,
        "maximum_loss_abs_difference": maximum_loss,
        "cases": per_case,
    }


def _semantic_hash(values: tuple[float, ...]) -> str:
    quantized = tuple(round(value / TOLERANCE) for value in values)
    return sha256_bytes(struct.pack(f"<{len(quantized)}q", *quantized))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _qpc() -> tuple[int, int]:
    counter = ctypes.c_longlong()
    frequency = ctypes.c_longlong()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel32.QueryPerformanceCounter(ctypes.byref(counter)):
        raise OSError(ctypes.get_last_error(), "QueryPerformanceCounter failed")
    if not kernel32.QueryPerformanceFrequency(ctypes.byref(frequency)):
        raise OSError(ctypes.get_last_error(), "QueryPerformanceFrequency failed")
    return counter.value, frequency.value


def _thread_cycles() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThread.restype = ctypes.c_void_p
    kernel32.QueryThreadCycleTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)]
    kernel32.QueryThreadCycleTime.restype = ctypes.c_int
    cycles = ctypes.c_ulonglong()
    if not kernel32.QueryThreadCycleTime(kernel32.GetCurrentThread(), ctypes.byref(cycles)):
        raise OSError(ctypes.get_last_error(), "QueryThreadCycleTime failed")
    return cycles.value


def _pin_current_thread(cpu: int) -> None:
    if sys.platform != "win32":
        raise RuntimeError("the frozen full-worker affinity contract requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThread.restype = ctypes.c_void_p
    kernel32.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel32.SetThreadAffinityMask.restype = ctypes.c_size_t
    if not kernel32.SetThreadAffinityMask(kernel32.GetCurrentThread(), 1 << cpu):
        raise OSError(ctypes.get_last_error(), "SetThreadAffinityMask failed")


def _render_native_worker(code: bytes) -> str:
    code_values = ",".join(str(value) for value in code)
    return f'''use std::env;
use std::ffi::c_void;
use std::fs::{{self, File}};
use std::io::{{Write}};
use std::ptr::copy_nonoverlapping;
use std::time::Instant;

const RECORDS: usize = {RECORDS};
const INPUTS: usize = {INPUT_FEATURES};
const HIDDEN: usize = {HIDDEN_FEATURES};
const PARAMS: usize = {PARAMETER_COUNT};
const EPOCHS: usize = {EPOCHS};

#[repr(C)]
struct LearnContext {{
    inputs: *const f64, targets: *const f64, parameters: *mut f64,
    gradients: *mut f64, records: usize, epochs: usize, learning_rate: f64,
    initial_loss: *mut f64, final_loss: *mut f64,
    epochs_completed: *mut u64, forward_epochs: *mut u64,
    backward_epochs: *mut u64, optimizer_steps: *mut u64,
    records_visited: *mut u64, parameter_writes: *mut u64,
}}

#[link(name="kernel32")]
extern "system" {{
    fn VirtualAlloc(address:*mut c_void,size:usize,allocation:u32,protect:u32)->*mut c_void;
    fn VirtualProtect(address:*mut c_void,size:usize,protect:u32,old:*mut u32)->i32;
    fn VirtualFree(address:*mut c_void,size:usize,free_type:u32)->i32;
    fn QueryPerformanceCounter(value:*mut i64)->i32;
    fn QueryPerformanceFrequency(value:*mut i64)->i32;
    fn QueryThreadCycleTime(thread:*mut c_void,cycles:*mut u64)->i32;
    fn GetCurrentThread()->*mut c_void;
    fn SetThreadAffinityMask(thread:*mut c_void,mask:usize)->usize;
}}
type Entry = unsafe extern "sysv64" fn(*mut LearnContext)->i32;

fn u32_at(raw:&[u8],offset:usize)->u32 {{ u32::from_le_bytes(raw[offset..offset+4].try_into().unwrap()) }}
fn u64_at(raw:&[u8],offset:usize)->u64 {{ u64::from_le_bytes(raw[offset..offset+8].try_into().unwrap()) }}
fn f64_at(raw:&[u8],offset:usize)->f64 {{ f64::from_bits(u64_at(raw,offset)) }}
fn push_u32(out:&mut Vec<u8>,value:u32) {{ out.extend_from_slice(&value.to_le_bytes()); }}
fn push_u64(out:&mut Vec<u8>,value:u64) {{ out.extend_from_slice(&value.to_le_bytes()); }}
fn push_f64(out:&mut Vec<u8>,value:f64) {{ push_u64(out,value.to_bits()); }}

fn predict(row:&[f64],p:&[f64])->f64 {{
    let mut hidden=[0.0f64;HIDDEN];
    let b1=INPUTS*HIDDEN; let w2=b1+HIDDEN; let b2=w2+HIDDEN;
    for j in 0..HIDDEN {{ hidden[j]=p[b1+j]; }}
    for k in 0..INPUTS {{ for j in 0..HIDDEN {{ hidden[j]+=row[k]*p[k*HIDDEN+j]; }} }}
    let mut value=p[b2];
    for j in 0..HIDDEN {{ value+=(if hidden[j]>0.0 {{hidden[j]}} else {{0.0}})*p[w2+j]; }}
    value
}}

fn main() {{
    let args:Vec<String>=env::args().collect();
    if args.len()!=6 && args.len()!=7 {{ std::process::exit(2); }}
    let dataset=fs::read(&args[1]).unwrap();
    let initializations=fs::read(&args[2]).unwrap();
    let start:usize=args[3].parse().unwrap(); let count:usize=args[4].parse().unwrap();
    let output_path=&args[5];
    let marker_path=if args.len()==7 {{Some(&args[6])}} else {{None}};
    unsafe {{ if SetThreadAffinityMask(GetCurrentThread(),1usize<<{AFFINITY_CPU})==0 {{ std::process::exit(10); }} }}
    if &dataset[0..8]!=b"FWDATA1\0" || u32_at(&dataset,8) as usize!=RECORDS || u32_at(&dataset,12) as usize!=INPUTS {{ std::process::exit(3); }}
    if &initializations[0..8]!=b"FWINIT1\0" {{ std::process::exit(4); }}
    let case_count=u32_at(&initializations,8) as usize;
    if count==0 || start+count>case_count {{ std::process::exit(5); }}
    let mut inputs=Vec::with_capacity(RECORDS*INPUTS); let mut cursor=24usize;
    for _ in 0..RECORDS*INPUTS {{ inputs.push(f64_at(&dataset,cursor)); cursor+=8; }}
    let mut targets=Vec::with_capacity(RECORDS);
    for _ in 0..RECORDS {{ targets.push(f64_at(&dataset,cursor)); cursor+=8; }}
    let code=[{code_values}u8];
    unsafe {{
        let memory=VirtualAlloc(std::ptr::null_mut(),code.len(),0x3000,0x04);
        if memory.is_null() {{ std::process::exit(6); }}
        copy_nonoverlapping(code.as_ptr(),memory.cast::<u8>(),code.len());
        let mut old=0u32; if VirtualProtect(memory,code.len(),0x20,&mut old)==0 {{ std::process::exit(7); }}
        let entry:Entry=std::mem::transmute(memory);
        let mut out=Vec::new(); out.extend_from_slice(b"FWRES1\0\0"); push_u32(&mut out,count as u32); push_u32(&mut out,RECORDS as u32);
        let start_unix_ns=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let mut qpc_frequency=0i64; let mut qpc_start=0i64; let mut qpc_end=0i64;
        let mut cycles_start=0u64; let mut cycles_end=0u64;
        QueryPerformanceFrequency(&mut qpc_frequency); QueryPerformanceCounter(&mut qpc_start);
        QueryThreadCycleTime(GetCurrentThread(),&mut cycles_start);
        let instant=Instant::now();
        let case_stride=44+PARAMS*8;
        for case_index in start..start+count {{
            let mut position=28+case_index*case_stride;
            let case_id=u32_at(&initializations,position); position+=4;
            let seed=u64_at(&initializations,position); position+=8;
            let nonce=&initializations[position..position+32]; position+=32;
            let mut parameters=[0.0f64;PARAMS]; for q in 0..PARAMS {{ parameters[q]=f64_at(&initializations,position); position+=8; }}
            let mut gradients=[0.0f64;PARAMS]; let mut initial_loss=0.0; let mut final_loss=0.0;
            let mut epochs=0u64; let mut forward=0u64; let mut backward=0u64; let mut steps=0u64; let mut visited=0u64; let mut writes=0u64;
            let mut context=LearnContext {{ inputs:inputs.as_ptr(),targets:targets.as_ptr(),parameters:parameters.as_mut_ptr(),gradients:gradients.as_mut_ptr(),records:RECORDS,epochs:EPOCHS,learning_rate:0.018,initial_loss:&mut initial_loss,final_loss:&mut final_loss,epochs_completed:&mut epochs,forward_epochs:&mut forward,backward_epochs:&mut backward,optimizer_steps:&mut steps,records_visited:&mut visited,parameter_writes:&mut writes }};
            if entry(&mut context)!=0 {{ std::process::exit(8); }}
            push_u32(&mut out,case_index as u32); push_u32(&mut out,case_id); push_u64(&mut out,seed); out.extend_from_slice(nonce);
            for value in [epochs,forward,backward,steps,visited,writes] {{ push_u64(&mut out,value); }}
            push_f64(&mut out,initial_loss); push_f64(&mut out,final_loss);
            for value in parameters {{ push_f64(&mut out,value); }}
            for i in 0..RECORDS {{ push_f64(&mut out,predict(&inputs[i*INPUTS..(i+1)*INPUTS],&parameters)); }}
        }}
        let mut file=File::create(output_path).unwrap(); file.write_all(&out).unwrap(); file.sync_all().unwrap();
        let elapsed=instant.elapsed().as_nanos(); QueryThreadCycleTime(GetCurrentThread(),&mut cycles_end); QueryPerformanceCounter(&mut qpc_end);
        let end_unix_ns=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        if let Some(path)=marker_path {{ let mut markers=File::create(path).unwrap(); writeln!(markers,"START {{}}",start_unix_ns).unwrap(); writeln!(markers,"END {{}}",end_unix_ns).unwrap(); markers.sync_all().unwrap(); }}
        println!("RESULT {{}} {{}} {{}} {{}} {{}} {{}} {{}} {{}}",start,count,elapsed,qpc_end-qpc_start,qpc_frequency,cycles_end-cycles_start,start_unix_ns,end_unix_ns);
        if VirtualFree(memory,0,0x8000)==0 {{ std::process::exit(9); }}
    }}
}}
'''


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--eager", action="store_true")
    parser.add_argument("--tcap", type=Path, required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markers", type=Path)
    args = parser.parse_args()
    if not args.eager:
        raise SystemExit("only --eager is implemented by the Python entry point")
    print(json.dumps(run_eager_worker(args.tcap, args.start, args.count, args.output, marker_path=args.markers), separators=(",", ":")), flush=True)
