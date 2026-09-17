from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .api import check_source
from .learn_canary import build_flood_canary
from .learn_native import (
    LEARN_NATIVE_TARGET,
    LearnNativeError,
    _compile_native,
    _git_commit,
    _linker_script,
    lower_learn_native,
    portable_ir_document,
    render_native_rust,
)
from .tcap import TcapSegment, build_tcap, canonical_json, parse_tcap
from .training import generate_training_dataset, parse_training_file


CORRECTNESS_CANARY = "CORRECTNESS_CANARY"
SCIENTIFIC_WORK_UNIT = "SCIENTIFIC_WORK_UNIT"
FULL_WORK_UNIT_SCHEMA = "casulo-flood-work-unit/1.0"
FULL_WORK_UNIT_ABI = "casulo-learn-context-sysv64-counters/1.0"
DATASET_MAGIC = b"FWDATA1\0"
INITIALIZATION_MAGIC = b"FWINIT1\0"
DATASET_HEADER = struct.Struct("<8sIIII")
INITIALIZATION_HEADER = struct.Struct("<8sIIIQ")
CASE_HEADER = struct.Struct("<IQ32s")
RECORDS = 1_024
EPOCHS = 400
INPUT_FEATURES = 8
HIDDEN_FEATURES = 8
OUTPUT_FEATURES = 1
PARAMETER_COUNT = 81
DEFAULT_CASES = 128
DATASET_SEED = 20_260_730


@dataclass(frozen=True, slots=True)
class WorkUnitContract:
    workload_class: str
    work_unit_schema: str
    records_per_epoch: int
    epochs: int
    batch_size: int
    input_features: int
    hidden_features: int
    output_features: int
    precision: str
    optimizer: str
    learning_rate: float
    dataset_hash: str
    initialization_bundle_hash: str
    expected_record_visits: int
    expected_optimizer_steps: int
    expected_parameter_writes: int
    scientific_eligible: bool
    general_ir_sha256: str
    graph_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        expected = {
            "workload_class": SCIENTIFIC_WORK_UNIT,
            "work_unit_schema": FULL_WORK_UNIT_SCHEMA,
            "records_per_epoch": RECORDS,
            "epochs": EPOCHS,
            "batch_size": RECORDS,
            "input_features": INPUT_FEATURES,
            "hidden_features": HIDDEN_FEATURES,
            "output_features": OUTPUT_FEATURES,
            "precision": "float64",
            "optimizer": "sgd",
            "expected_record_visits": RECORDS * EPOCHS,
            "expected_optimizer_steps": EPOCHS,
            "expected_parameter_writes": PARAMETER_COUNT * EPOCHS,
            "scientific_eligible": True,
        }
        for name, value in expected.items():
            if getattr(self, name) != value:
                raise ValueError(f"scientific work-unit contract mismatch: {name}")
        for name in (
            "dataset_hash",
            "initialization_bundle_hash",
            "general_ir_sha256",
            "graph_sha256",
        ):
            value = getattr(self, name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"scientific work-unit contract has invalid {name}")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("scientific work-unit learning rate is invalid")


@dataclass(frozen=True, slots=True)
class FullWorkUnitArtifact:
    tcap_file: Path
    contract_file: Path
    dataset_file: Path
    initialization_file: Path
    native_source_file: Path
    native_binary_file: Path
    tcap_sha256: str


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _initial_parameters(seed: int) -> tuple[float, ...]:
    import numpy as np

    generator = np.random.default_rng(seed)
    first = generator.normal(0.0, math.sqrt(1.0 / INPUT_FEATURES), INPUT_FEATURES * HIDDEN_FEATURES)
    bias = np.zeros(HIDDEN_FEATURES, dtype=np.float64)
    second = generator.normal(0.0, math.sqrt(1.0 / HIDDEN_FEATURES), HIDDEN_FEATURES)
    output_bias = np.zeros(1, dtype=np.float64)
    return tuple(float(value) for value in np.concatenate((first, bias, second, output_bias)))


def build_dataset_payload(source_path: Path) -> tuple[bytes, dict[str, Any]]:
    spec = parse_training_file(source_path)
    dataset = generate_training_dataset(spec, records=RECORDS, seed=DATASET_SEED)
    inputs = dataset.inputs.astype("<f8", copy=False).tobytes(order="C")
    targets = dataset.targets.astype("<f8", copy=False).tobytes(order="C")
    header = DATASET_HEADER.pack(DATASET_MAGIC, RECORDS, INPUT_FEATURES, 1, 64)
    raw = header + inputs + targets
    return raw, {
        "schema": "casulo-flood-dataset-binary/1.0",
        "records": RECORDS,
        "input_features": INPUT_FEATURES,
        "target_features": 1,
        "precision": "float64-little-endian",
        "alignment": 8,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "generator_dataset_sha256": dataset.sha256,
        "seed": DATASET_SEED,
    }


def build_initialization_payload(case_count: int = DEFAULT_CASES) -> tuple[bytes, dict[str, Any]]:
    if not 1 <= case_count <= 4096:
        raise ValueError("scientific initialization case count is outside bounds")
    payload = bytearray(
        INITIALIZATION_HEADER.pack(
            INITIALIZATION_MAGIC, case_count, PARAMETER_COUNT, 64, 0xC45120260808
        )
    )
    cases = []
    for index in range(case_count):
        seed = 260_730 + index * 104_729
        case_id = index + 1
        nonce = hashlib.sha256(f"casulo-full-worker:{case_id}:{seed}".encode("ascii")).digest()
        parameters = _initial_parameters(seed)
        parameter_raw = struct.pack(f"<{PARAMETER_COUNT}d", *parameters)
        payload.extend(CASE_HEADER.pack(case_id, seed, nonce))
        payload.extend(parameter_raw)
        cases.append(
            {
                "case_id": f"case-{case_id:04d}",
                "index": index,
                "seed": seed,
                "nonce": nonce.hex(),
                "initial_parameters_sha256": sha256_bytes(parameter_raw),
            }
        )
    raw = bytes(payload)
    return raw, {
        "schema": "casulo-flood-initialization-bundle/1.0",
        "cases": cases,
        "case_count": case_count,
        "parameter_count": PARAMETER_COUNT,
        "precision": "float64-little-endian",
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "all_nonces_unique": len({item["nonce"] for item in cases}) == case_count,
        "all_parameter_hashes_unique": len(
            {item["initial_parameters_sha256"] for item in cases}
        ) == case_count,
    }


def build_full_work_unit_tcap(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    case_count: int = DEFAULT_CASES,
) -> FullWorkUnitArtifact:
    source_file = Path(source_path).resolve(strict=True)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_text = source_file.read_text(encoding="utf-8")
    checked = check_source(source_text, file=str(source_file))
    errors = [item.render() for item in checked.diagnostics if item.severity.value == "error"]
    if errors or checked.ir is None or checked.graph is None:
        raise LearnNativeError("general T pipeline rejected source:\n" + "\n".join(errors))
    plan = lower_learn_native(checked.ir, checked.graph)
    if (plan.input_features, plan.hidden_features, plan.output_features, plan.epochs) != (
        INPUT_FEATURES,
        HIDDEN_FEATURES,
        OUTPUT_FEATURES,
        EPOCHS,
    ):
        raise ValueError("T general pipeline does not describe FloodSurrogate V1")

    dataset_raw, dataset_manifest = build_dataset_payload(source_file)
    initialization_raw, initialization_manifest = build_initialization_payload(case_count)
    contract = WorkUnitContract(
        workload_class=SCIENTIFIC_WORK_UNIT,
        work_unit_schema=FULL_WORK_UNIT_SCHEMA,
        records_per_epoch=RECORDS,
        epochs=EPOCHS,
        batch_size=RECORDS,
        input_features=INPUT_FEATURES,
        hidden_features=HIDDEN_FEATURES,
        output_features=OUTPUT_FEATURES,
        precision="float64",
        optimizer="sgd",
        learning_rate=plan.learning_rate,
        dataset_hash=dataset_manifest["sha256"],
        initialization_bundle_hash=initialization_manifest["sha256"],
        expected_record_visits=RECORDS * EPOCHS,
        expected_optimizer_steps=EPOCHS,
        expected_parameter_writes=PARAMETER_COUNT * EPOCHS,
        scientific_eligible=True,
        general_ir_sha256=plan.ir_sha256,
        graph_sha256=plan.graph_sha256,
    )
    contract.validate()
    contract_raw = canonical_json(contract.to_dict())

    native_source = output / "FloodSurrogate.full.native.rs"
    linker = output / "FloodSurrogate.full.ld"
    elf = output / "FloodSurrogate.full.elf"
    binary = output / "FloodSurrogate.full.bin"
    native_source.write_text(
        render_native_rust(plan, runtime_counters=True), encoding="utf-8", newline="\n"
    )
    linker.write_text(_linker_script(), encoding="utf-8", newline="\n")
    toolchain = _compile_native(native_source, linker, elf, binary)
    code = binary.read_bytes()
    canary = build_flood_canary(plan).to_bytes()
    compiler = {
        "name": "casulo-t-general-ir-full-worker",
        "version": "1.0+rustc-" + toolchain["rustc_release"],
        "commit": _git_commit(source_file.parent),
    }
    raw = build_tcap(
        segments=(
            TcapSegment("code", code, "rx", alignment=16),
            TcapSegment("plan", canonical_json(plan.to_dict()), "r"),
            TcapSegment("ir", canonical_json(portable_ir_document(checked.ir)), "r"),
            TcapSegment("graph", canonical_json(checked.graph.to_dict()), "r"),
            TcapSegment("source", source_text.encode("utf-8"), "r"),
            TcapSegment("canary", canary, "r", alignment=8),
            TcapSegment("scientific_dataset", dataset_raw, "r", alignment=8),
            TcapSegment("initialization_bundle", initialization_raw, "r", alignment=8),
            TcapSegment("work_unit_contract", contract_raw, "r", alignment=8),
        ),
        target=LEARN_NATIVE_TARGET,
        abi=FULL_WORK_UNIT_ABI,
        entry_segment="code",
        entry_offset=0,
        compiler=compiler,
        resource_contract=plan.resource_contract,
    )
    parse_tcap(raw)
    tcap_file = output / "FloodSurrogate.full.tcap"
    tcap_file.write_bytes(raw)
    dataset_file = output / "FloodSurrogate.dataset.bin"
    initialization_file = output / "FloodSurrogate.initializations.bin"
    contract_file = output / "FloodSurrogate.work-unit.json"
    dataset_file.write_bytes(dataset_raw)
    initialization_file.write_bytes(initialization_raw)
    contract_file.write_text(
        json.dumps(contract.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output / "initialization_bundle.json").write_text(
        json.dumps(initialization_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return FullWorkUnitArtifact(
        tcap_file=tcap_file,
        contract_file=contract_file,
        dataset_file=dataset_file,
        initialization_file=initialization_file,
        native_source_file=native_source,
        native_binary_file=binary,
        tcap_sha256=sha256_bytes(raw),
    )


def load_full_work_unit_tcap(path: str | Path) -> tuple[WorkUnitContract, dict[str, bytes]]:
    package = parse_tcap(Path(path).read_bytes())
    if package.manifest["abi"] != FULL_WORK_UNIT_ABI:
        raise ValueError("TCAP does not use the scientific full-worker ABI")
    segments = {item.name: item.data for item in package.segments}
    required = {
        "code",
        "plan",
        "ir",
        "graph",
        "source",
        "canary",
        "scientific_dataset",
        "initialization_bundle",
        "work_unit_contract",
    }
    if set(segments) != required:
        raise ValueError("scientific TCAP segment set is incomplete")
    contract = WorkUnitContract(**json.loads(segments["work_unit_contract"]))
    contract.validate()
    plan = json.loads(segments["plan"])
    if sha256_bytes(segments["ir"]) != contract.general_ir_sha256:
        raise ValueError("general IR hash differs from compiled contract")
    if sha256_bytes(segments["graph"]) != contract.graph_sha256:
        raise ValueError("graph hash differs from compiled contract")
    if plan.get("ir_sha256") != contract.general_ir_sha256:
        raise ValueError("plan IR hash differs from compiled contract")
    if plan.get("graph_sha256") != contract.graph_sha256:
        raise ValueError("plan graph hash differs from compiled contract")
    if plan.get("learning_rate") != contract.learning_rate:
        raise ValueError("plan learning rate differs from compiled contract")
    if plan.get("epochs") != contract.epochs:
        raise ValueError("plan epochs differ from compiled contract")
    if sha256_bytes(segments["scientific_dataset"]) != contract.dataset_hash:
        raise ValueError("scientific dataset hash differs from compiled contract")
    if sha256_bytes(segments["initialization_bundle"]) != contract.initialization_bundle_hash:
        raise ValueError("initialization bundle hash differs from compiled contract")
    return contract, segments
