from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .graph import GRAPH_LEARN_VERSION, MetamorfoseGraph
from .ir import IR_LEARN_VERSION, IRProgram
from .learn_canary import LearnCanary, build_flood_canary, verify_canary_oracle
from .resource import ResourceContract, SemanticClass
from .tcap import TcapSegment, build_tcap, canonical_json, parse_tcap


LEARN_NATIVE_PROTOCOL = "casulo-learn-native-plan/0.1"
LEARN_NATIVE_ABI = "casulo-learn-context-sysv64/0.1"
LEARN_NATIVE_TARGET = "x86_64-casulo-none"
LEARN_NATIVE_BACKEND = "casulo-t-general-ir-rust-aot/0.1"
LEARN_MAX_RECORDS = 4096
_EXPECTED_OPS = (
    "learn.read",
    "learn.forward",
    "learn.loss",
    "learn.backward",
    "learn.optimize",
    "learn.stop",
)


class LearnNativeError(RuntimeError):
    """The general learn IR cannot be lowered without changing semantics."""


@dataclass(frozen=True, slots=True)
class LearnNativePlan:
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
    instruction_ops: tuple[str, ...]
    graph_node_kinds: tuple[str, ...]
    ir_sha256: str
    graph_sha256: str
    max_records: int
    resource_contract: ResourceContract

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["instruction_ops"] = list(self.instruction_ops)
        result["graph_node_kinds"] = list(self.graph_node_kinds)
        result["resource_contract"] = self.resource_contract.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class LearnTcapArtifact:
    directory: Path
    tcap_file: Path
    evidence_file: Path
    plan_file: Path
    native_source_file: Path
    native_elf_file: Path
    native_binary_file: Path
    artifact_sha256: str
    content_sha256: str
    entry_offset: int
    compiler: dict[str, str]


def lower_learn_native(ir: IRProgram, graph: MetamorfoseGraph) -> LearnNativePlan:
    """Lower the general, versioned IR and graph into a bounded native plan.

    This function deliberately has no dependency on ``training.py``.  The old
    training parser can compare its view with this plan, but cannot construct
    or mutate the plan used by the native backend.
    """

    if ir.version != IR_LEARN_VERSION or graph.version != GRAPH_LEARN_VERSION:
        raise LearnNativeError("learn native lowering requires IR/graph 0.2")
    if ir.module is None or graph.module != ir.module:
        raise LearnNativeError("IR and graph module provenance differ")
    learn_operations = tuple(item for item in ir.operations if item.kind == "learn")
    if len(learn_operations) != 1 or len(ir.operations) != 1:
        raise LearnNativeError("backend 0.1 accepts exactly one learn operation")
    operation = learn_operations[0]
    graph_operations = tuple(
        item for item in graph.operations if item.name == operation.name
    )
    if len(graph_operations) != 1 or len(graph.operations) != 1:
        raise LearnNativeError("IR and graph operation sets differ")
    operation_graph = graph_operations[0]
    ops = tuple(item.op for item in operation.instructions)
    if ops != _EXPECTED_OPS:
        raise LearnNativeError(f"unsupported learn instruction sequence: {ops!r}")
    graph_kinds = tuple(
        node.kind for node in operation_graph.nodes if node.kind.startswith("learn.")
    )
    if graph_kinds != _EXPECTED_OPS:
        raise LearnNativeError("Metamorfose graph does not preserve learn sequence")
    if operation.contract is None:
        raise LearnNativeError("learn operation has no semantic contract")
    contract = operation.contract
    required = {
        "module",
        "name",
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
        "permissions",
        "effects",
        "deterministic",
    }
    missing = required - set(contract)
    if missing:
        raise LearnNativeError(f"learn contract fields missing: {sorted(missing)}")
    if contract["module"] != ir.module or contract["name"] != operation.name:
        raise LearnNativeError("contract identity differs from IR identity")
    if tuple(contract["permissions"]) != operation_graph.permissions:
        raise LearnNativeError("permissions differ between IR contract and graph")
    if not contract["deterministic"] or not operation_graph.deterministic:
        raise LearnNativeError("backend 0.1 requires deterministic learn semantics")

    input_features = _strict_positive_int(contract["input_features"], "input_features")
    hidden_features = _strict_positive_int(
        contract["hidden_features"], "hidden_features"
    )
    output_features = _strict_positive_int(
        contract["output_features"], "output_features"
    )
    if output_features != 1:
        raise LearnNativeError("backend 0.1 requires one output")
    parameter_count = input_features * hidden_features + hidden_features * 2 + 1
    dataset_bytes = LEARN_MAX_RECORDS * (input_features + output_features) * 8
    arena_bytes = (parameter_count + 1) * 8
    memory_limit = max(
        4096, _align(dataset_bytes + arena_bytes + parameter_count * 8, 4096)
    )
    resource = ResourceContract(
        memory_limit_bytes=memory_limit,
        arena_bytes=arena_bytes,
        max_threads=1,
        semantic_class=SemanticClass.FLOW,
        deterministic=True,
        numerical_precision=str(contract["precision"]),
        permissions=("memory", "console"),
        quality_definition={
            "protocol": "casulo-learn-equivalence/0.1",
            "loss": str(contract["loss"]),
            "target_loss": float(contract["target_loss"]),
            "max_abs_parameter_difference": 1e-9,
            "max_prediction_rmse_difference": 1e-9,
        },
        residual_routing={
            "audit": "ATTRACTOR_AUDIT",
            "retry": "ATTRACTOR_RETRY",
            "invalid": "QUARANTINE",
        },
    )
    return LearnNativePlan(
        protocol=LEARN_NATIVE_PROTOCOL,
        module=ir.module,
        name=operation.name,
        input_features=input_features,
        hidden_features=hidden_features,
        output_features=output_features,
        activation=_strict_text(contract["activation"], "activation"),
        loss=_strict_text(contract["loss"], "loss"),
        optimizer=_strict_text(contract["optimizer"], "optimizer"),
        learning_rate=float(contract["learning_rate"]),
        epochs=_strict_positive_int(contract["epochs"], "epochs"),
        precision=_strict_text(contract["precision"], "precision"),
        batch=_strict_text(contract["batch"], "batch"),
        seed=int(contract["seed"]),
        target_loss=float(contract["target_loss"]),
        instruction_ops=ops,
        graph_node_kinds=graph_kinds,
        ir_sha256=_json_sha256(portable_ir_document(ir)),
        graph_sha256=_json_sha256(graph.to_dict()),
        max_records=LEARN_MAX_RECORDS,
        resource_contract=resource,
    )


def compare_legacy_oracle(plan: LearnNativePlan, source: str) -> dict[str, Any]:
    """Compare against the historical parser without using it for codegen."""

    from .training import parse_training_spec

    legacy = parse_training_spec(source)
    fields = (
        "module",
        "name",
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
    )
    differences = {
        name: {"general": getattr(plan, name), "legacy": getattr(legacy, name)}
        for name in fields
        if getattr(plan, name) != getattr(legacy, name)
    }
    return {
        "protocol": "casulo-learn-legacy-oracle/0.1",
        "role": "equivalence-comparator-only",
        "passed": not differences,
        "differences": differences,
    }


def build_learn_tcap(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    commit: str | None = None,
) -> LearnTcapArtifact:
    """Compile one general ``learn`` program and package a real native TCAP."""

    from .api import check_source

    source_file = Path(source_path).expanduser().resolve(strict=True)
    source = source_file.read_text(encoding="utf-8")
    checked = check_source(source, file=str(source_file))
    errors = [
        item.render() for item in checked.diagnostics if item.severity.value == "error"
    ]
    if errors or checked.ir is None or checked.graph is None:
        raise LearnNativeError(
            "general T pipeline rejected source:\n" + "\n".join(errors)
        )
    plan = lower_learn_native(checked.ir, checked.graph)
    oracle = compare_legacy_oracle(plan, source)
    if not oracle["passed"]:
        raise LearnNativeError("legacy oracle differs from the general learn plan")

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan_bytes = canonical_json(plan.to_dict())
    ir_bytes = canonical_json(portable_ir_document(checked.ir))
    graph_bytes = canonical_json(checked.graph.to_dict())
    source_bytes = source.encode("utf-8")
    canary = build_flood_canary(plan)
    canary_bytes = canary.to_bytes()
    canary_oracle = verify_canary_oracle(canary)
    rust_source = render_native_rust(plan)
    native_source = output / "FloodSurrogate.native.rs"
    linker_script = output / "FloodSurrogate.ld"
    native_elf = output / "FloodSurrogate.elf"
    native_binary = output / "FloodSurrogate.bin"
    native_source.write_text(rust_source, encoding="utf-8", newline="\n")
    linker_script.write_text(_linker_script(), encoding="utf-8", newline="\n")
    toolchain = _compile_native(native_source, linker_script, native_elf, native_binary)
    code = native_binary.read_bytes()
    if not code:
        raise LearnNativeError("native linker produced an empty payload")
    runtime_audit = _runtime_audit_raw(code, canary, native_binary.parent)
    toolchain["runtime_position_independent_audit"] = runtime_audit

    resolved_commit = commit or _git_commit(source_file.parent)
    compiler = {
        "name": "casulo-t-general-ir",
        "version": "0.1+rustc-" + toolchain["rustc_release"],
        "commit": resolved_commit,
    }
    raw = build_tcap(
        segments=(
            TcapSegment("code", code, "rx", alignment=16),
            TcapSegment("plan", plan_bytes, "r"),
            TcapSegment("ir", ir_bytes, "r"),
            TcapSegment("graph", graph_bytes, "r"),
            TcapSegment("source", source_bytes, "r"),
            TcapSegment("canary", canary_bytes, "r", alignment=8),
        ),
        target=LEARN_NATIVE_TARGET,
        abi=LEARN_NATIVE_ABI,
        entry_segment="code",
        entry_offset=0,
        compiler=compiler,
        resource_contract=plan.resource_contract,
    )
    parsed = parse_tcap(raw)
    corrupted = bytearray(raw)
    corrupted[-1] ^= 0x01
    corruption_rejected = False
    try:
        parse_tcap(bytes(corrupted))
    except ValueError:
        corruption_rejected = True
    if not corruption_rejected:
        raise LearnNativeError("TCAP corruption self-test did not fail closed")
    tcap_file = output / "FloodSurrogate.tcap"
    tcap_file.write_bytes(raw)
    plan_file = output / "FloodSurrogate.plan.json"
    plan_file.write_bytes(plan_bytes + b"\n")
    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    (output / "FloodSurrogate.tcap.sha256").write_text(
        f"{artifact_sha256}  FloodSurrogate.tcap\n",
        encoding="ascii",
        newline="\n",
    )
    evidence = {
        "protocol": "casulo-learn-tcap-evidence/0.1",
        "artifact": {
            "file": tcap_file.name,
            "sha256": artifact_sha256,
            "content_sha256": parsed.manifest["content_sha256"],
            "target": LEARN_NATIVE_TARGET,
            "abi": LEARN_NATIVE_ABI,
            "entry_offset": 0,
        },
        "pipeline": {
            "path": [
                "T",
                "AST",
                "Larva analysis",
                "Crisalida IR",
                "Metamorfose graph",
                "native plan",
                "Rust AOT",
                "TCAP",
            ],
            "ir_sha256": plan.ir_sha256,
            "graph_sha256": plan.graph_sha256,
            "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "native_source_sha256": hashlib.sha256(
                rust_source.encode("utf-8")
            ).hexdigest(),
            "native_binary_sha256": hashlib.sha256(code).hexdigest(),
            "canary_sha256": hashlib.sha256(canary_bytes).hexdigest(),
        },
        "compiler": {**compiler, "underlying_toolchain": toolchain},
        "resource_contract": plan.resource_contract.to_dict(),
        "equivalence": {
            "general_ir_graph_conformance": "PASS",
            "legacy_oracle": oracle,
            "host_numerical_canary": {**canary_oracle, "status": "PASS"},
            "raw_host_runtime_audit": runtime_audit,
            "native_kernel_execution": "NOT_RUN",
            "quality_gate": "BLOCKED_KERNEL_EXECUTION",
            "reason": "host builder cannot substitute for isolated Casulo OS execution",
        },
        "negative_validation": {
            "single_byte_segment_corruption": "REJECTED",
            "legacy_divergence_policy": "REJECT_BUILD",
            "unsupported_ir_or_graph_policy": "REJECT_BUILD",
        },
        "energy": {"status": "unavailable", "joules": None},
        "claims": {
            "native_payload_built": True,
            "tcap_integrity_validated": True,
            "kernel_execution_proven": False,
            "numerical_equivalence_proven_on_kernel": False,
            "host_canary_oracle_equivalence_proven": True,
            "raw_payload_executed_at_dynamic_host_address": runtime_audit["status"]
            == "PASS",
            "performance_measured": False,
        },
        "canary_scope": {
            "role": "bounded-correctness-canary",
            "not_a_performance_campaign": True,
            "historical_performance_record_count": 1024,
            "records": canary.records,
            "epochs": canary.epochs,
            "float_loop_order": "casulo-learn-f64-loop-order/1",
            "segment": "canary",
            "segment_bytes": len(canary_bytes),
            "segment_sha256": hashlib.sha256(canary_bytes).hexdigest(),
            "tolerance": canary.tolerance,
            "expected_initial_loss": canary.expected_initial_loss,
            "expected_final_loss": canary.expected_final_loss,
            "target_loss": canary.target_loss,
        },
    }
    evidence_file = output / "FloodSurrogate.evidence.json"
    evidence_file.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return LearnTcapArtifact(
        directory=output,
        tcap_file=tcap_file,
        evidence_file=evidence_file,
        plan_file=plan_file,
        native_source_file=native_source,
        native_elf_file=native_elf,
        native_binary_file=native_binary,
        artifact_sha256=artifact_sha256,
        content_sha256=parsed.manifest["content_sha256"],
        entry_offset=0,
        compiler=compiler,
    )


def render_native_rust(
    plan: LearnNativePlan, *, runtime_counters: bool = False
) -> str:
    if plan.activation != "relu" or plan.loss != "mse" or plan.optimizer != "sgd":
        raise LearnNativeError("native payload 0.1 supports relu/mse/sgd only")
    counter_fields = """
    pub epochs_completed: *mut u64,
    pub forward_epochs: *mut u64,
    pub backward_epochs: *mut u64,
    pub optimizer_steps: *mut u64,
    pub records_visited: *mut u64,
    pub parameter_writes: *mut u64,""" if runtime_counters else ""
    counter_null_guard = """
        || ctx.epochs_completed.is_null() || ctx.forward_epochs.is_null()
        || ctx.backward_epochs.is_null() || ctx.optimizer_steps.is_null()
        || ctx.records_visited.is_null() || ctx.parameter_writes.is_null()""" if runtime_counters else ""
    counter_initialization = """
    *ctx.epochs_completed = 0;
    *ctx.forward_epochs = 0;
    *ctx.backward_epochs = 0;
    *ctx.optimizer_steps = 0;
    *ctx.records_visited = 0;
    *ctx.parameter_writes = 0;""" if runtime_counters else ""
    counter_after_batch = """
        *ctx.forward_epochs += 1;
        *ctx.backward_epochs += 1;
        *ctx.records_visited += ctx.records as u64;""" if runtime_counters else ""
    counter_after_update = """
        *ctx.optimizer_steps += 1;
        *ctx.parameter_writes += PARAMS as u64;
        *ctx.epochs_completed += 1;""" if runtime_counters else ""
    return f"""#![no_std]
#![no_main]

const INPUTS: usize = {plan.input_features};
const HIDDEN: usize = {plan.hidden_features};
const PARAMS: usize = INPUTS * HIDDEN + HIDDEN + HIDDEN + 1;
const EPOCHS: usize = {plan.epochs};
const LEARNING_RATE: f64 = {plan.learning_rate!r};
const MAX_RECORDS: usize = {plan.max_records};

#[repr(C)]
pub struct LearnContext {{
    pub inputs: *const f64,
    pub targets: *const f64,
    pub parameters: *mut f64,
    pub gradients: *mut f64,
    pub records: usize,
    pub epochs: usize,
    pub learning_rate: f64,
    pub initial_loss: *mut f64,
    pub final_loss: *mut f64,
{counter_fields}
}}

#[inline(always)]
fn relu(value: f64) -> f64 {{ if value > 0.0 {{ value }} else {{ 0.0 }} }}

unsafe fn predict(row: *const f64, parameters: *const f64) -> f64 {{
    let mut hidden = [0.0f64; HIDDEN];
    let b1 = INPUTS * HIDDEN;
    let w2 = b1 + HIDDEN;
    let b2 = w2 + HIDDEN;
    let mut j = 0;
    while j < HIDDEN {{ hidden[j] = *parameters.add(b1 + j); j += 1; }}
    let mut k = 0;
    while k < INPUTS {{
        let input = *row.add(k);
        j = 0;
        while j < HIDDEN {{
            hidden[j] += input * *parameters.add(k * HIDDEN + j);
            j += 1;
        }}
        k += 1;
    }}
    let mut output = *parameters.add(b2);
    j = 0;
    while j < HIDDEN {{ output += relu(hidden[j]) * *parameters.add(w2 + j); j += 1; }}
    output
}}

unsafe fn evaluate(ctx: &LearnContext) -> f64 {{
    let mut total = 0.0;
    let mut i = 0;
    while i < ctx.records {{
        let error = predict(ctx.inputs.add(i * INPUTS), ctx.parameters) - *ctx.targets.add(i);
        total += error * error;
        i += 1;
    }}
    total / ctx.records as f64
}}

#[unsafe(no_mangle)]
#[unsafe(link_section = ".text.entry")]
pub unsafe extern "sysv64" fn casulo_learn_entry(context: *mut LearnContext) -> i32 {{
    if context.is_null() {{ return -1; }}
    let ctx = &mut *context;
    if ctx.inputs.is_null() || ctx.targets.is_null() || ctx.parameters.is_null()
        || ctx.gradients.is_null() || ctx.initial_loss.is_null() || ctx.final_loss.is_null()
        {counter_null_guard} {{ return -2; }}
    if ctx.records == 0 || ctx.records > MAX_RECORDS {{ return -3; }}
    if ctx.epochs != EPOCHS || ctx.learning_rate.to_bits() != LEARNING_RATE.to_bits() {{ return -4; }}
{counter_initialization}
    *ctx.initial_loss = evaluate(ctx);
    let mut epoch = 0;
    while epoch < EPOCHS {{
        let mut q = 0;
        while q < PARAMS {{ *ctx.gradients.add(q) = 0.0; q += 1; }}
        let mut i = 0;
        while i < ctx.records {{
            let row = ctx.inputs.add(i * INPUTS);
            let mut pre = [0.0f64; HIDDEN];
            let mut hidden = [0.0f64; HIDDEN];
            let mut delta = [0.0f64; HIDDEN];
            let b1 = INPUTS * HIDDEN;
            let w2 = b1 + HIDDEN;
            let b2 = w2 + HIDDEN;
            let mut j = 0;
            while j < HIDDEN {{ pre[j] = *ctx.parameters.add(b1 + j); j += 1; }}
            let mut k = 0;
            while k < INPUTS {{
                let input = *row.add(k);
                j = 0;
                while j < HIDDEN {{ pre[j] += input * *ctx.parameters.add(k * HIDDEN + j); j += 1; }}
                k += 1;
            }}
            let mut prediction = *ctx.parameters.add(b2);
            j = 0;
            while j < HIDDEN {{
                hidden[j] = relu(pre[j]);
                prediction += hidden[j] * *ctx.parameters.add(w2 + j);
                j += 1;
            }}
            let output_gradient = (2.0 / ctx.records as f64) * (prediction - *ctx.targets.add(i));
            *ctx.gradients.add(b2) += output_gradient;
            j = 0;
            while j < HIDDEN {{
                let derivative = if pre[j] > 0.0 {{ 1.0 }} else {{ 0.0 }};
                delta[j] = output_gradient * *ctx.parameters.add(w2 + j) * derivative;
                *ctx.gradients.add(w2 + j) += output_gradient * hidden[j];
                *ctx.gradients.add(b1 + j) += delta[j];
                j += 1;
            }}
            k = 0;
            while k < INPUTS {{
                let input = *row.add(k);
                j = 0;
                while j < HIDDEN {{
                    *ctx.gradients.add(k * HIDDEN + j) += delta[j] * input;
                    j += 1;
                }}
                k += 1;
            }}
            i += 1;
        }}
{counter_after_batch}
        q = 0;
        while q < PARAMS {{
            *ctx.parameters.add(q) -= LEARNING_RATE * *ctx.gradients.add(q);
            q += 1;
        }}
{counter_after_update}
        epoch += 1;
    }}
    *ctx.final_loss = evaluate(ctx);
    0
}}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {{ loop {{ core::hint::spin_loop(); }} }}
"""


def _compile_native(
    source: Path, linker: Path, elf: Path, binary: Path
) -> dict[str, Any]:
    rustc = _rustc()
    sysroot_process = subprocess.run(
        [str(rustc), "--print", "sysroot"], capture_output=True, text=True, check=False
    )
    if sysroot_process.returncode != 0:
        raise LearnNativeError(
            "cannot determine Rust sysroot: " + sysroot_process.stderr.strip()
        )
    sysroot = Path(sysroot_process.stdout.strip())
    llvm_bin = sysroot / "lib" / "rustlib" / "x86_64-pc-windows-msvc" / "bin"
    target_lib = sysroot / "lib" / "rustlib" / "x86_64-unknown-none" / "lib"
    linker_exe = llvm_bin / "rust-lld.exe"
    objcopy = llvm_bin / "llvm-objcopy.exe"
    readobj = llvm_bin / "llvm-readobj.exe"
    nm = llvm_bin / "llvm-nm.exe"
    for tool in (linker_exe, objcopy, readobj, nm):
        if not tool.is_file():
            raise LearnNativeError(f"required Rust llvm-tool is unavailable: {tool}")
    object_file = source.with_suffix(".o")
    compile_command = [
        str(rustc),
        str(source),
        "--crate-name",
        "casulo_flood_surrogate",
        "--target",
        "x86_64-unknown-none",
        "-C",
        "opt-level=2",
        "-C",
        "panic=abort",
        "-C",
        "relocation-model=pic",
        "-C",
        "target-feature=-soft-float,+sse,+sse2",
        "--emit=obj",
        "-o",
        str(object_file),
    ]
    process = subprocess.run(
        compile_command, capture_output=True, text=True, check=False
    )
    if process.returncode != 0 or not object_file.is_file():
        raise LearnNativeError(
            f"native Rust compilation failed ({process.returncode}): {(process.stderr or process.stdout).strip()}"
        )
    builtins = tuple(target_lib.glob("libcompiler_builtins-*.rlib"))
    if len(builtins) != 1:
        raise LearnNativeError(
            "pinned target compiler_builtins is unavailable or ambiguous"
        )
    link_command = [
        str(linker_exe),
        "-flavor",
        "gnu",
        str(object_file),
        str(builtins[0]),
        "-o",
        str(elf),
        "-T",
        str(linker),
        "--build-id=none",
        "--gc-sections",
    ]
    process = subprocess.run(link_command, capture_output=True, text=True, check=False)
    if process.returncode != 0 or not elf.is_file():
        raise LearnNativeError(
            f"freestanding link failed ({process.returncode}): {(process.stderr or process.stdout).strip()}"
        )
    copy_process = subprocess.run(
        [str(objcopy), "-O", "binary", str(elf), str(binary)],
        capture_output=True,
        text=True,
        check=False,
    )
    if copy_process.returncode != 0 or not binary.is_file():
        raise LearnNativeError(
            f"native extraction failed ({copy_process.returncode}): {(copy_process.stderr or copy_process.stdout).strip()}"
        )
    relocation = subprocess.run(
        [str(readobj), "--relocations", str(elf)],
        capture_output=True,
        text=True,
        check=False,
    )
    if relocation.returncode != 0 or "Section (" in relocation.stdout:
        raise LearnNativeError("linked native payload retains relocations")
    symbols = subprocess.run(
        [str(nm), "--defined-only", str(elf)],
        capture_output=True,
        text=True,
        check=False,
    )
    entry_addresses = []
    for line in symbols.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] == "casulo_learn_entry":
            entry_addresses.append(int(parts[0], 16))
    if symbols.returncode != 0 or entry_addresses != [0x1000]:
        raise LearnNativeError(
            f"native entry symbol is not uniquely fixed at raw offset zero: {entry_addresses}"
        )
    static_audit = _audit_self_contained_elf(
        elf=elf,
        readobj=readobj,
        nm=nm,
        objdump=llvm_bin / "llvm-objdump.exe",
    )
    version = subprocess.run(
        [str(rustc), "--version", "--verbose"],
        capture_output=True,
        text=True,
        check=False,
    )
    values = dict(
        line.split(":", 1) for line in version.stdout.splitlines() if ":" in line
    )
    return {
        "rustc_release": values.get("release", "unknown").strip(),
        "rustc_commit": values.get("commit-hash", "unknown").strip(),
        "llvm_version": values.get("LLVM version", "unknown").strip(),
        "target": "x86_64-unknown-none",
        "relocations": "none",
        "entry_virtual_address": "0x1000",
        "raw_entry_offset": 0,
        "float_execution": "sse2-hard-float-memory-context",
        "position_independent_audit": static_audit,
    }


def _rustc() -> Path:
    rustup = shutil.which("rustup")
    if rustup is None:
        raise LearnNativeError("rustup is required for the pinned native toolchain")
    process = subprocess.run(
        [rustup, "which", "--toolchain", "nightly-2026-02-01", "rustc"],
        capture_output=True,
        text=True,
        check=False,
    )
    path = Path(process.stdout.strip())
    if process.returncode != 0 or not path.is_file():
        raise LearnNativeError("pinned nightly-2026-02-01 rustc is unavailable")
    return path


def _audit_self_contained_elf(
    *, elf: Path, readobj: Path, nm: Path, objdump: Path
) -> dict[str, Any]:
    """Reject a raw image that depends on linkage data outside itself.

    A relocation-free ELF is insufficient: a linker script can discard GOT
    storage after resolving references to its former low virtual addresses.
    This audit therefore checks the final linked image and its disassembly.
    The RP0.1 payload does not use callbacks, so every indirect call/jump is
    rejected rather than guessed safe.
    """

    if not objdump.is_file():
        raise LearnNativeError(f"required Rust llvm-tool is unavailable: {objdump}")
    sections = subprocess.run(
        [str(readobj), "--sections", str(elf)],
        capture_output=True,
        text=True,
        check=False,
    )
    if sections.returncode != 0:
        raise LearnNativeError("cannot inspect final ELF sections")
    undefined = subprocess.run(
        [str(nm), "--undefined-only", str(elf)],
        capture_output=True,
        text=True,
        check=False,
    )
    if undefined.returncode != 0:
        raise LearnNativeError(
            "cannot inspect final ELF undefined symbols: " + undefined.stderr.strip()
        )
    disassembly = subprocess.run(
        [str(objdump), "-d", str(elf)],
        capture_output=True,
        text=True,
        check=False,
    )
    if disassembly.returncode != 0:
        raise LearnNativeError("cannot disassemble final native payload")
    return _validate_self_contained_inspection(
        sections=sections.stdout,
        undefined_symbols=undefined.stdout,
        disassembly=disassembly.stdout,
    )


def _validate_self_contained_inspection(
    *, sections: str, undefined_symbols: str, disassembly: str
) -> dict[str, Any]:
    forbidden_sections = tuple(
        name
        for name in (".got", ".got.plt", ".plt", ".plt.got")
        if re.search(
            rf"^\s*Name:\s+{re.escape(name)}(?:\s|$)", sections, re.MULTILINE
        )
    )
    if forbidden_sections:
        raise LearnNativeError(
            "linked native payload retains forbidden linkage sections: "
            + ", ".join(forbidden_sections)
        )
    if undefined_symbols.strip():
        raise LearnNativeError(
            "linked native payload retains undefined symbols: "
            + undefined_symbols.strip()
        )
    lowered = disassembly.lower()
    linkage_tokens = tuple(
        token for token in ("gotpcrel", "@got", "@plt", ".got", ".plt") if token in lowered
    )
    if linkage_tokens:
        raise LearnNativeError(
            "native disassembly retains GOT/PLT linkage: " + ", ".join(linkage_tokens)
        )
    indirect_transfers = tuple(
        line.strip()
        for line in disassembly.splitlines()
        if re.search(r"\b(?:callq?|jmpq?)\s+\*", line)
    )
    if indirect_transfers:
        raise LearnNativeError(
            "native disassembly retains indirect control transfer: "
            + indirect_transfers[0]
        )
    low_page_references = tuple(
        line.strip()
        for line in disassembly.splitlines()
        for match in re.finditer(r"#\s*0x([0-9a-fA-F]+)", line)
        if int(match.group(1), 16) < 0x1000
    )
    if low_page_references:
        raise LearnNativeError(
            "native disassembly references the unmapped low page: "
            + low_page_references[0]
        )
    return {
        "protocol": "casulo-raw-aot-self-contained-audit/1.0",
        "status": "PASS",
        "forbidden_linkage_sections": "absent",
        "undefined_symbols": "absent",
        "got_plt_references": "absent",
        "indirect_control_transfers": "absent",
        "low_page_references": "absent",
    }


def _runtime_audit_raw(
    code: bytes, canary: LearnCanary, working_directory: Path
) -> dict[str, Any]:
    """Execute the exact raw image at an OS-selected address on Windows.

    The pinned toolchain supports a System V function pointer in a Windows
    host executable, so the compiler generates the cross-ABI boundary and
    preserves Windows nonvolatile XMM registers.  Other hosts report the gate
    unavailable; they do not silently claim execution.
    """

    if sys.platform != "win32":
        return {
            "protocol": "casulo-raw-aot-runtime-audit/1.0",
            "status": "unavailable",
            "reason": "Windows sysv64 host harness is not available on this host",
        }
    rustc = _rustc()
    source = _render_windows_runtime_audit(code, canary)
    with tempfile.TemporaryDirectory(
        prefix=".casulo-runtime-audit-", dir=working_directory
    ) as temporary:
        directory = Path(temporary)
        harness = directory / "runtime_audit.rs"
        executable = directory / "runtime_audit.exe"
        harness.write_text(source, encoding="utf-8", newline="\n")
        compiled = subprocess.run(
            [
                str(rustc),
                str(harness),
                "--edition=2021",
                "-C",
                "opt-level=0",
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if compiled.returncode != 0 or not executable.is_file():
            raise LearnNativeError(
                "raw runtime-audit harness compilation failed: "
                + (compiled.stderr or compiled.stdout).strip()
            )
        executed = _run_runtime_audit_executable(executable)
    expected = "RUNTIME_AUDIT=PASS\n"
    if executed.returncode != 0 or executed.stdout != expected:
        raise LearnNativeError(
            f"raw runtime audit failed ({executed.returncode}): "
            + (executed.stderr or executed.stdout).strip()
        )
    return {
        "protocol": "casulo-raw-aot-runtime-audit/1.0",
        "status": "PASS",
        "loaded_at_link_address": False,
        "abi": LEARN_NATIVE_ABI,
        "records": canary.records,
        "epochs": canary.epochs,
        "tolerance": canary.tolerance,
        "quality_target_met": True,
    }


def _run_runtime_audit_executable(executable: Path) -> subprocess.CompletedProcess[str]:
    """Run a fresh audit binary despite bounded Windows scanner races."""
    attempts = 10 if sys.platform == "win32" else 1
    for attempt in range(1, attempts + 1):
        try:
            return subprocess.run(
                [str(executable)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except PermissionError as exc:
            if getattr(exc, "winerror", None) != 5 or attempt == attempts:
                raise
            time.sleep(0.25)
    raise AssertionError("unreachable runtime-audit retry state")


def _render_windows_runtime_audit(code: bytes, canary: LearnCanary) -> str:
    def byte_array(values: bytes) -> str:
        return ",".join(str(value) for value in values)

    # Preserve exact binary64 bits; no decimal-source round trip is involved.
    def bits_array(values: tuple[float, ...]) -> str:
        import struct

        return ",".join(
            f"f64::from_bits(0x{struct.unpack('<Q', struct.pack('<d', value))[0]:016x})"
            for value in values
        )

    return f"""use std::ffi::c_void;
use std::ptr::copy_nonoverlapping;

#[repr(C)]
struct LearnContext {{
    inputs: *const f64,
    targets: *const f64,
    parameters: *mut f64,
    gradients: *mut f64,
    records: usize,
    epochs: usize,
    learning_rate: f64,
    initial_loss: *mut f64,
    final_loss: *mut f64,
}}

#[link(name = "kernel32")]
extern "system" {{
    fn VirtualAlloc(address: *mut c_void, size: usize, allocation: u32, protect: u32) -> *mut c_void;
    fn VirtualFree(address: *mut c_void, size: usize, free_type: u32) -> i32;
}}

type Entry = unsafe extern "sysv64" fn(*mut LearnContext) -> i32;

fn main() {{
    let code = [{byte_array(code)}u8];
    let inputs = [{bits_array(canary.inputs)}];
    let targets = [{bits_array(canary.targets)}];
    let mut parameters = [{bits_array(canary.initial_parameters)}];
    let expected = [{bits_array(canary.expected_final_parameters)}];
    let mut gradients = [0.0f64; {canary.parameter_count}];
    let mut initial_loss = 0.0f64;
    let mut final_loss = 0.0f64;
    unsafe {{
        let memory = VirtualAlloc(std::ptr::null_mut(), code.len(), 0x3000, 0x40);
        if memory.is_null() || memory as usize == 0x1000 {{ std::process::exit(10); }}
        copy_nonoverlapping(code.as_ptr(), memory.cast::<u8>(), code.len());
        let entry: Entry = std::mem::transmute(memory);
        let mut context = LearnContext {{
            inputs: inputs.as_ptr(), targets: targets.as_ptr(),
            parameters: parameters.as_mut_ptr(), gradients: gradients.as_mut_ptr(),
            records: {canary.records}, epochs: {canary.epochs},
            learning_rate: f64::from_bits(0x{_float_bits(canary.learning_rate):016x}),
            initial_loss: &mut initial_loss, final_loss: &mut final_loss,
        }};
        if entry(&mut context) != 0 {{ std::process::exit(11); }}
        let mut maximum = 0.0f64;
        for index in 0..parameters.len() {{ maximum = maximum.max((parameters[index] - expected[index]).abs()); }}
        if (initial_loss - f64::from_bits(0x{_float_bits(canary.expected_initial_loss):016x})).abs() > {canary.tolerance!r}
            || (final_loss - f64::from_bits(0x{_float_bits(canary.expected_final_loss):016x})).abs() > {canary.tolerance!r}
            || maximum > {canary.tolerance!r} || final_loss > {canary.target_loss!r}
        {{ std::process::exit(12); }}
        if VirtualFree(memory, 0, 0x8000) == 0 {{ std::process::exit(13); }}
    }}
    println!("RUNTIME_AUDIT=PASS");
}}
"""


def _float_bits(value: float) -> int:
    import struct

    return struct.unpack("<Q", struct.pack("<d", value))[0]


def _linker_script() -> str:
    return """ENTRY(casulo_learn_entry)
SECTIONS
{
  . = 0x1000;
  .text : ALIGN(16) { KEEP(*(.text.entry)) *(.text .text.*) }
  .rodata : ALIGN(16) { *(.rodata .rodata.*) }
  .data : ALIGN(16) { *(.data .data.*) }
  .got : ALIGN(8) { *(.got .got.*) }
  .plt : ALIGN(16) { *(.plt .plt.*) }
  /DISCARD/ : { *(.eh_frame*) *(.comment*) *(.note*) }
}
"""


def _git_commit(start: Path) -> str:
    root_process = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if root_process.returncode != 0:
        return "uncommitted-source+tree-unknown"

    root = Path(root_process.stdout.strip()).resolve()
    compiler_paths = tuple(
        sorted(
            (path for path in (root / "src" / "casulo" / "t").rglob("*.py")),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    project_file = root / "pyproject.toml"
    if project_file.is_file():
        compiler_paths += (project_file,)
    if not compiler_paths:
        return "uncommitted-source+tree-empty"

    source_tree = hashlib.sha256()
    for path in compiler_paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        source_tree.update(len(relative).to_bytes(4, "little"))
        source_tree.update(relative)
        source_tree.update(len(content).to_bytes(8, "little"))
        source_tree.update(content)
    tree_sha256 = source_tree.hexdigest()

    head_process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    head = (
        head_process.stdout.strip()
        if head_process.returncode == 0 and head_process.stdout.strip()
        else "uncommitted-source"
    )
    status_process = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "src/casulo/t",
            "pyproject.toml",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if status_process.returncode != 0 or status_process.stdout.strip():
        return f"{head}+dirty-tree-{tree_sha256}"
    return head


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def portable_ir_document(ir: IRProgram) -> dict[str, Any]:
    """Return distributable IR without checkout-specific source locations."""

    return _without_source_spans(ir.to_dict())


def _without_source_spans(value: Any) -> Any:
    if type(value) is dict:
        return {
            key: _without_source_spans(item)
            for key, item in value.items()
            if key != "span"
        }
    if type(value) in (list, tuple):
        return [_without_source_spans(item) for item in value]
    return value


def _strict_positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise LearnNativeError(f"{name} must be a positive integer")
    return value


def _strict_text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise LearnNativeError(f"{name} must be a non-empty string")
    return value


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)
