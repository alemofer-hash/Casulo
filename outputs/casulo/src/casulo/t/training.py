from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import math
import os
import platform
import random
import re
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .native import _compiler_version, _find_compiler
from .learn import LearnContractError, validate_learn_contract
from .learn_native import (
    LEARN_NATIVE_PROTOCOL,
    LearnNativePlan,
    compare_legacy_oracle,
    lower_learn_native,
)
from .pytorch_runtime import (
    configure_pytorch_inductor,
    prepare_pytorch_inductor_runtime,
)


TRAINING_SPEC_PROTOCOL = "casulo-training-spec/0.1"
TRAINING_ARTIFACT_PROTOCOL = "casulo-training-artifact/0.1"
TRAINING_ABI_PROTOCOL = "casulo-training-abi/0.1"
TRAINING_BENCHMARK_PROTOCOL = "casulo-training-benchmark/0.1"
TRAINING_BACKEND = "c99-openmp-fused/0.4"
TRAINING_DATASET_PROTOCOL = "casulo-hydrology-surrogate/0.1"
PYTORCH_EAGER_BASELINE = "pytorch-eager-cpu"
PYTORCH_COMPILE_BASELINE = "pytorch-compile-inductor-cpu"
PYTORCH_BASELINES = (
    PYTORCH_EAGER_BASELINE,
    PYTORCH_COMPILE_BASELINE,
)
FEATURE_NAMES = (
    "precipitation",
    "soil_moisture",
    "slope",
    "impervious_fraction",
    "upstream_flow",
    "wind_setup",
    "pressure_anomaly",
    "pump_availability",
)


class TrainingError(RuntimeError):
    pass


class TrainingSpecError(TrainingError):
    pass


class TrainingCompilationError(TrainingError):
    pass


@dataclass(frozen=True, slots=True)
class TrainingSpec:
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TrainingDataset:
    inputs: Any
    targets: Any
    validation_inputs: Any
    validation_targets: Any
    sha256: str
    seed: int
    feature_names: tuple[str, ...]

    @property
    def records(self) -> int:
        return int(self.inputs.shape[0])

    def manifest(self) -> dict[str, Any]:
        return {
            "protocol": TRAINING_DATASET_PROTOCOL,
            "sha256": self.sha256,
            "records": self.records,
            "validation_records": int(self.validation_inputs.shape[0]),
            "features": int(self.inputs.shape[1]),
            "feature_names": list(self.feature_names),
            "seed": self.seed,
            "precision": "float64",
            "target": "normalized_peak_level_proxy",
        }


@dataclass(frozen=True, slots=True)
class TrainingArtifact:
    directory: Path
    artifact_id: str
    manifest: dict[str, Any]
    source_file: Path
    c_file: Path


@dataclass(frozen=True, slots=True)
class TrainingBuild:
    library: Path
    compiler: str
    compiler_version: str
    command: tuple[str, ...]
    binary_sha256: str
    source_sha256: str
    vectorization_report: tuple[str, ...]
    openmp: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "library": str(self.library),
            "command": list(self.command),
            "vectorization_report": list(self.vectorization_report),
        }


@dataclass(frozen=True, slots=True)
class TrainingOutcome:
    backend: str
    initial_loss: float
    final_loss: float
    validation_loss: float
    parameter_sha256: str
    prediction_sha256: str
    parameters: Any
    predictions: Any


@dataclass(frozen=True, slots=True)
class TrainingMeasurement:
    name: str
    samples: int
    wall_ns_samples: tuple[int, ...]
    cpu_ns_samples: tuple[int, ...]
    median_wall_ns: int
    median_cpu_ns: int


@dataclass(frozen=True, slots=True)
class TrainingExperimentReport:
    protocol: str
    artifact_id: str
    dataset: dict[str, Any]
    model: dict[str, Any]
    environment: dict[str, Any]
    scientific: dict[str, Any]
    baseline: dict[str, Any]
    compiler: dict[str, Any]
    quality: dict[str, Any]
    pytorch: TrainingMeasurement
    casulo_t: TrainingMeasurement
    comparison: dict[str, Any]
    outcomes: dict[str, Any]
    energy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_training_spec(source: str) -> TrainingSpec:
    lines: list[tuple[int, str]] = []
    for line_number, raw in enumerate(source.splitlines(), 1):
        content = raw.split("#", 1)[0].strip()
        if content:
            lines.append((line_number, content))
    if not lines:
        raise TrainingSpecError("fonte de treinamento vazia")

    module = None
    name = None
    values: dict[str, str] = {}
    for line_number, content in lines:
        parts = content.split()
        if parts[0] == "module":
            if module is not None or len(parts) != 2:
                raise TrainingSpecError(
                    f"linha {line_number}: declaração module inválida"
                )
            module = parts[1]
            continue
        if parts[0] == "learn":
            if name is not None or len(parts) != 2:
                raise TrainingSpecError(
                    f"linha {line_number}: declaração learn inválida"
                )
            name = parts[1]
            continue
        if name is None:
            raise TrainingSpecError(
                f"linha {line_number}: propriedade antes de learn"
            )
        if len(parts) != 2:
            raise TrainingSpecError(
                f"linha {line_number}: esperado 'propriedade valor'"
            )
        key, value = parts
        if key in values:
            raise TrainingSpecError(
                f"linha {line_number}: propriedade duplicada: {key}"
            )
        values[key] = value

    if module is None or name is None:
        raise TrainingSpecError("module e learn são obrigatórios")
    identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
    if not identifier.fullmatch(module) or not identifier.fullmatch(name):
        raise TrainingSpecError("module ou learn contém identificador inválido")

    try:
        contract = validate_learn_contract(
            module=module,
            name=name,
            values=values,
        )
    except LearnContractError as error:
        raise TrainingSpecError(str(error)) from error
    return TrainingSpec(
        module=contract.module,
        name=contract.name,
        input_features=contract.input_features,
        hidden_features=contract.hidden_features,
        output_features=contract.output_features,
        activation=contract.activation,
        loss=contract.loss,
        optimizer=contract.optimizer,
        learning_rate=contract.learning_rate,
        epochs=contract.epochs,
        precision=contract.precision,
        batch=contract.batch,
        seed=contract.seed,
        target_loss=contract.target_loss,
    )


def parse_training_file(path: str | Path) -> TrainingSpec:
    return parse_training_spec(
        Path(path).expanduser().resolve().read_text(encoding="utf-8")
    )


def generate_training_dataset(
    spec: TrainingSpec,
    *,
    records: int,
    seed: int,
) -> TrainingDataset:
    if records < 32:
        raise TrainingError("dataset exige ao menos 32 registros")
    if spec.input_features != len(FEATURE_NAMES):
        raise TrainingError(
            f"dataset 0.1 exige {len(FEATURE_NAMES)} variáveis de entrada"
        )
    np = _numpy()
    generator = np.random.default_rng(seed)
    validation_records = max(128, records // 4)
    total = records + validation_records
    raw = np.empty((total, len(FEATURE_NAMES)), dtype=np.float64)
    raw[:, 0] = generator.gamma(2.2, 18.0, total)
    raw[:, 1] = generator.beta(4.0, 2.0, total)
    raw[:, 2] = generator.uniform(0.0, 0.35, total)
    raw[:, 3] = generator.beta(2.0, 3.5, total)
    raw[:, 4] = generator.lognormal(2.6, 0.55, total)
    raw[:, 5] = generator.normal(0.0, 1.0, total)
    raw[:, 6] = generator.normal(0.0, 9.0, total)
    raw[:, 7] = generator.uniform(0.45, 1.0, total)
    train_raw = raw[:records]
    x = (raw - train_raw.mean(axis=0)) / train_raw.std(axis=0)
    target = (
        0.52 * x[:, 0]
        + 0.38 * x[:, 1]
        + 0.14 * x[:, 0] * x[:, 1]
        + 0.18 * x[:, 3]
        + 0.27 * x[:, 4]
        + 0.11 * np.tanh(x[:, 5])
        - 0.08 * x[:, 6]
        - 0.24 * x[:, 7]
        + 0.06 * x[:, 2] * x[:, 3]
    )
    train_target = target[:records]
    y = ((target - train_target.mean()) / train_target.std()).astype(
        np.float64,
        copy=False,
    )
    train_x = np.ascontiguousarray(x[:records], dtype=np.float64)
    train_y = np.ascontiguousarray(y[:records], dtype=np.float64)
    validation_x = np.ascontiguousarray(x[records:], dtype=np.float64)
    validation_y = np.ascontiguousarray(y[records:], dtype=np.float64)
    digest = hashlib.sha256()
    digest.update(TRAINING_DATASET_PROTOCOL.encode("ascii"))
    digest.update(str(seed).encode("ascii"))
    digest.update(train_x.tobytes(order="C"))
    digest.update(train_y.tobytes(order="C"))
    digest.update(validation_x.tobytes(order="C"))
    digest.update(validation_y.tobytes(order="C"))
    return TrainingDataset(
        inputs=train_x,
        targets=train_y,
        validation_inputs=validation_x,
        validation_targets=validation_y,
        sha256=digest.hexdigest(),
        seed=seed,
        feature_names=FEATURE_NAMES,
    )


def initial_parameters(spec: TrainingSpec) -> Any:
    np = _numpy()
    generator = np.random.default_rng(spec.seed)
    first = generator.normal(
        0.0,
        math.sqrt(1.0 / spec.input_features),
        spec.input_features * spec.hidden_features,
    )
    bias = np.zeros(spec.hidden_features, dtype=np.float64)
    second = generator.normal(
        0.0,
        math.sqrt(1.0 / spec.hidden_features),
        spec.hidden_features,
    )
    output_bias = np.zeros(1, dtype=np.float64)
    return np.ascontiguousarray(
        np.concatenate((first, bias, second, output_bias)),
        dtype=np.float64,
    )


def build_training_artifact(
    source_path: str | Path,
    output_dir: str | Path,
) -> TrainingArtifact:
    source_file = Path(source_path).expanduser().resolve()
    source = source_file.read_text(encoding="utf-8")
    plan = _lower_general_training_pipeline(source, source_file)
    oracle = compare_legacy_oracle(plan, source)
    if not oracle["passed"]:
        raise TrainingSpecError(
            "divergencia entre pipeline geral e oraculo legado: "
            + json.dumps(oracle["differences"], sort_keys=True)
        )
    spec = _training_spec_from_plan(plan)
    lowering = {
        "protocol": LEARN_NATIVE_PROTOCOL,
        "ir_sha256": plan.ir_sha256,
        "graph_sha256": plan.graph_sha256,
        "legacy_role": "equivalence-comparator-only",
    }
    canonical = json.dumps(
        {
            "protocol": TRAINING_ARTIFACT_PROTOCOL,
            "spec": spec.to_dict(),
            "source_sha256": _sha256(source.encode("utf-8")),
            "backend": TRAINING_BACKEND,
            "abi": TRAINING_ABI_PROTOCOL,
            "lowering": lowering,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    artifact_id = "sha256:" + _sha256(canonical.encode("utf-8"))
    c_source = _render_training_c(plan, artifact_id)
    source_sha256 = _sha256(source.encode("utf-8"))
    native_source_sha256 = _sha256(c_source.encode("utf-8"))
    directory = Path(output_dir).expanduser().resolve()
    manifest_path = directory / "manifest.json"
    if directory.exists():
        if not manifest_path.is_file():
            raise TrainingError(
                f"destino existente não é artefato de treinamento: {directory}"
            )
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if saved.get("artifact_id") != artifact_id:
            raise TrainingError(
                f"destino contém outro artefato: {directory}"
            )
        expected_manifest_fields = {
            "protocol": TRAINING_ARTIFACT_PROTOCOL,
            "source": {"file": "source.t", "sha256": source_sha256},
            "spec": spec.to_dict(),
            "backend": TRAINING_BACKEND,
            "abi": TRAINING_ABI_PROTOCOL,
            "lowering": lowering,
            "native_source": {
                "file": "casulo_training.c",
                "sha256": native_source_sha256,
            },
        }
        for field, expected in expected_manifest_fields.items():
            if saved.get(field) != expected:
                raise TrainingError(
                    f"manifesto de treinamento adulterado no campo {field}: "
                    f"{directory}"
                )
        stored_source = directory / "source.t"
        c_file = directory / "casulo_training.c"
        try:
            stored_source_text = stored_source.read_text(encoding="utf-8")
            stored_native_text = c_file.read_text(encoding="utf-8")
        except OSError as error:
            raise TrainingError(
                f"artefato de treinamento incompleto: {directory}"
            ) from error
        if stored_source_text != source or stored_native_text != c_source:
            raise TrainingError(
                f"conteúdo do artefato de treinamento adulterado: {directory}"
            )
        return TrainingArtifact(
            directory=directory,
            artifact_id=artifact_id,
            manifest=saved,
            source_file=stored_source,
            c_file=c_file,
        )
    directory.mkdir(parents=True)
    stored_source = directory / "source.t"
    c_file = directory / "casulo_training.c"
    stored_source.write_text(source, encoding="utf-8", newline="\n")
    c_file.write_text(c_source, encoding="utf-8", newline="\n")
    manifest = {
        "protocol": TRAINING_ARTIFACT_PROTOCOL,
        "artifact_id": artifact_id,
        "brand": {
            "invention": "Casulo",
            "origin": "Teloscorp",
            "specialty": "Otimização de Tráfego de Informação",
        },
        "source": {
            "file": "source.t",
            "sha256": source_sha256,
        },
        "spec": spec.to_dict(),
        "backend": TRAINING_BACKEND,
        "abi": TRAINING_ABI_PROTOCOL,
        "lowering": lowering,
        "native_source": {
            "file": "casulo_training.c",
            "sha256": native_source_sha256,
        },
        "semantics": {
            "precision": "float64",
            "reassociation": False,
            "fast_math": False,
            "training": "full-batch-gradient-descent",
            "reduction": "contiguous-partitions-worker-order",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return TrainingArtifact(
        directory=directory,
        artifact_id=artifact_id,
        manifest=manifest,
        source_file=stored_source,
        c_file=c_file,
    )


def _lower_general_training_pipeline(
    source: str,
    source_file: Path,
) -> LearnNativePlan:
    """Form the code-generating plan from general T IR and graph.

    The historical parser runs afterwards only as a fail-closed oracle.
    """

    from .api import check_source

    checked = check_source(source, file=str(source_file))
    errors = [
        item.render()
        for item in checked.diagnostics
        if item.severity.value == "error"
    ]
    if errors:
        raise TrainingSpecError(
            "pipeline geral T rejeitou learn:\n" + "\n".join(errors)
        )
    if checked.ir is None or checked.graph is None:
        raise TrainingSpecError(
            "pipeline geral T não produziu contrato, IR e grafo para learn"
        )
    if (
        checked.ir.version != "crisalida-ir/0.2"
        or checked.graph.version != "metamorfose-graph/0.2"
    ):
        raise TrainingSpecError(
            "pipeline geral T produziu versão de IR ou grafo inesperada"
        )
    try:
        return lower_learn_native(checked.ir, checked.graph)
    except RuntimeError as error:
        raise TrainingSpecError(
            f"lowering nativo geral rejeitou learn: {error}"
        ) from error


def _training_spec_from_plan(plan: LearnNativePlan) -> TrainingSpec:
    return TrainingSpec(
        module=plan.module,
        name=plan.name,
        input_features=plan.input_features,
        hidden_features=plan.hidden_features,
        output_features=plan.output_features,
        activation=plan.activation,
        loss=plan.loss,
        optimizer=plan.optimizer,
        learning_rate=plan.learning_rate,
        epochs=plan.epochs,
        precision=plan.precision,
        batch=plan.batch,
        seed=plan.seed,
        target_loss=plan.target_loss,
    )


def compile_training_artifact(artifact: TrainingArtifact) -> TrainingBuild:
    compiler = _find_compiler()
    compiler_version = _compiler_version(compiler)
    name = compiler.name.lower()
    if "gcc" not in name and "clang" not in name:
        raise TrainingCompilationError(
            "backend de treinamento 0.1 exige GCC ou Clang com OpenMP"
        )
    source_sha256 = artifact.manifest["native_source"]["sha256"]
    cache_key = _sha256(
        (
            source_sha256
            + compiler_version
            + platform.machine()
            + platform.processor()
        ).encode("utf-8")
    )[:24]
    cache_root = Path(
        os.environ.get(
            "CASULO_NATIVE_CACHE",
            str(Path.home() / ".casulo-native"),
        )
    ).expanduser()
    target = cache_root / "training" / cache_key
    target.mkdir(parents=True, exist_ok=True)
    library = target / (
        "casulo_training.dll"
        if os.name == "nt"
        else (
            "libcasulo_training.dylib"
            if platform.system() == "Darwin"
            else "libcasulo_training.so"
        )
    )
    report_file = target / "vectorization.txt"
    command = [
        str(compiler),
        "-std=c99",
        "-O3",
        "-march=native",
        "-fno-fast-math",
        "-ffp-contract=off",
        "-fopenmp",
        "-shared",
    ]
    if os.name != "nt":
        command.extend(["-fPIC", "-fvisibility=hidden"])
    else:
        command.extend(
            ["-Wl,--no-insert-timestamp,--image-base,0x180000000", "-s"]
        )
    if "gcc" in name:
        command.append(f"-fopt-info-vec-optimized={report_file}")
    command.extend([str(artifact.c_file), "-o", str(library)])
    if os.name != "nt":
        command.append("-lm")

    rebuild = True
    build_manifest = target / "build.json"
    if library.is_file() and build_manifest.is_file():
        try:
            saved = json.loads(build_manifest.read_text(encoding="utf-8"))
            rebuild = not (
                saved.get("source_sha256") == source_sha256
                and saved.get("compiler_version") == compiler_version
                and saved.get("binary_sha256") == _file_sha256(library)
            )
        except (OSError, ValueError, json.JSONDecodeError):
            rebuild = True
    if rebuild:
        process = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
        if process.returncode != 0 or not library.is_file():
            detail = (process.stderr or process.stdout).strip()
            raise TrainingCompilationError(
                f"compilação do treino falhou ({process.returncode}): {detail}"
            )
        build_manifest.write_text(
            json.dumps(
                {
                    "protocol": "casulo-training-build/0.1",
                    "source_sha256": source_sha256,
                    "compiler": str(compiler),
                    "compiler_version": compiler_version,
                    "binary_sha256": _file_sha256(library),
                    "command": [
                        "$CC" if item == str(compiler) else (
                            "$CASULO_TRAINING_SOURCE"
                            if item == str(artifact.c_file)
                            else (
                                "$CASULO_TRAINING_LIBRARY"
                                if item == str(library)
                                else item
                            )
                        )
                        for item in command
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    try:
        vectorization = tuple(
            line.strip()
            for line in report_file.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
            if line.strip()
        )
    except OSError:
        vectorization = ()
    return TrainingBuild(
        library=library,
        compiler=str(compiler),
        compiler_version=compiler_version,
        command=tuple(command),
        binary_sha256=_file_sha256(library),
        source_sha256=source_sha256,
        vectorization_report=vectorization,
        openmp=True,
    )


def run_training_experiment(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    records: int = 1_024,
    samples: int = 9,
    warmups: int = 2,
    workers: int | str = "auto",
    seed: int = 20_260_730,
    bootstrap_resamples: int = 2_000,
    preregistration: str | Path | None = None,
    baseline: str = PYTORCH_EAGER_BASELINE,
) -> TrainingExperimentReport:
    if samples < 5:
        raise TrainingError("experimento exige ao menos 5 amostras pareadas")
    if warmups < 1:
        raise TrainingError("experimento exige aquecimento")
    if bootstrap_resamples < 200:
        raise TrainingError("bootstrap exige ao menos 200 reamostragens")
    if baseline not in PYTORCH_BASELINES:
        raise TrainingError(f"baseline PyTorch desconhecido: {baseline}")

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifact = build_training_artifact(source_path, output / "artifact")
    spec = TrainingSpec(**artifact.manifest["spec"])
    from .scientific import bind_training_preregistration

    scientific = bind_training_preregistration(
        preregistration,
        source_path,
        spec,
        observed_baseline=baseline,
        records=records,
        samples=samples,
        warmups=warmups,
        workers=workers,
        seed=seed,
        bootstrap_resamples=bootstrap_resamples,
    )
    scheduler = select_training_workers(spec, records, workers)
    selected_workers = scheduler["selected_workers"]
    dataset = generate_training_dataset(spec, records=records, seed=seed)
    initial = initial_parameters(spec)
    build = compile_training_artifact(artifact)
    native_train = _native_trainer(
        spec,
        dataset,
        initial,
        build,
        selected_workers,
    )
    if baseline == PYTORCH_COMPILE_BASELINE:
        torch_train, torch_metadata = _pytorch_compiled_trainer(
            spec,
            dataset,
            initial,
            selected_workers,
        )
    else:
        torch_train, torch_metadata = _pytorch_trainer(
            spec,
            dataset,
            initial,
            selected_workers,
        )

    torch_reference = torch_train()
    native_reference = native_train()
    torch_repeated = torch_train()
    native_repeated = native_train()
    quality = _quality_gate(
        spec,
        torch_reference,
        native_reference,
        torch_repeated,
        native_repeated,
    )

    for index in range(warmups):
        (torch_train if index % 2 == 0 else native_train)()
        (native_train if index % 2 == 0 else torch_train)()

    torch_wall: list[int] = []
    torch_cpu: list[int] = []
    native_wall: list[int] = []
    native_cpu: list[int] = []
    gc_enabled = gc.isenabled()
    try:
        gc.disable()
        for sample in range(samples):
            order: tuple[
                tuple[Callable[[], TrainingOutcome], list[int], list[int]],
                ...,
            ] = (
                (
                    (torch_train, torch_wall, torch_cpu),
                    (native_train, native_wall, native_cpu),
                )
                if sample % 2 == 0
                else (
                    (native_train, native_wall, native_cpu),
                    (torch_train, torch_wall, torch_cpu),
                )
            )
            for function, wall_values, cpu_values in order:
                wall, cpu = _measure_once(function)
                wall_values.append(wall)
                cpu_values.append(cpu)
    finally:
        if gc_enabled:
            gc.enable()

    torch_measurement = _training_measurement(
        baseline.replace("-", "_") + "_full_batch",
        torch_wall,
        torch_cpu,
    )
    native_measurement = _training_measurement(
        "casulo_t_c99_openmp_fused",
        native_wall,
        native_cpu,
    )
    paired = tuple(
        reference / native
        for reference, native in zip(torch_wall, native_wall)
        if native
    )
    ci = _bootstrap_median_ci(
        paired,
        resamples=bootstrap_resamples,
        seed=seed ^ 0xC451,
    )
    speedup = statistics.median(paired)
    report = TrainingExperimentReport(
        protocol=TRAINING_BENCHMARK_PROTOCOL,
        artifact_id=artifact.artifact_id,
        dataset=dataset.manifest(),
        model=spec.to_dict(),
        environment={
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "physical_scope": (
                "mesmo processo, mesmo dataset em memória, "
                f"{selected_workers} "
                f"{'worker' if selected_workers == 1 else 'workers'}"
            ),
            "scheduler": scheduler,
        },
        scientific=scientific,
        baseline=torch_metadata,
        compiler=build.to_dict(),
        quality=quality,
        pytorch=torch_measurement,
        casulo_t=native_measurement,
        comparison={
            "scope": (
                "treinamento completo em memória: forward, backward, "
                "SGD e perda final"
            ),
            "paired_speedup_median": speedup,
            "paired_speedup_samples": list(paired),
            "paired_speedup_ci95": ci,
            "ratio_of_medians": (
                torch_measurement.median_wall_ns
                / native_measurement.median_wall_ns
            ),
            "workers": selected_workers,
            "scheduler": scheduler,
            "claim_gate_6x": bool(
                scientific["claims_allowed"]
                and quality["equivalent_training"]
                and quality["quality_target_reached"]
                and ci["lower"] >= 6.0
            ),
            "claim": (
                "6x demonstrado no treinamento declarado"
                if (
                    scientific["claims_allowed"]
                    and quality["equivalent_training"]
                    and quality["quality_target_reached"]
                    and ci["lower"] >= 6.0
                )
                else "6x ainda não demonstrado neste treinamento"
            ),
        },
        outcomes={
            "initial_parameter_sha256": _array_sha256(initial),
            "pytorch": _outcome_summary(torch_reference),
            "casulo_t": _outcome_summary(native_reference),
        },
        energy={
            "electrical_energy_measured": False,
            "joules": None,
            "cpu_time_is_energy": False,
            "warning": (
                "tempo de CPU não é medição elétrica; joules exigem instrumento"
            ),
        },
    )
    _write_training_bundle(
        output,
        dataset,
        report,
    )
    return report


def select_training_workers(
    spec: TrainingSpec,
    records: int,
    requested: int | str,
) -> dict[str, Any]:
    if isinstance(requested, str) and requested != "auto":
        try:
            requested = int(requested)
        except ValueError as error:
            raise TrainingError(
                "workers precisa ser auto, 1, 2 ou 4"
            ) from error
    if requested != "auto" and requested not in {1, 2, 4}:
        raise TrainingError("workers precisa ser auto, 1, 2 ou 4")
    work_per_epoch = records * spec.input_features * spec.hidden_features
    if requested == "auto":
        if work_per_epoch < 262_144:
            selected = 1
            reason = (
                "lote compacto: sincronização custaria mais que a partição"
            )
        elif work_per_epoch < 1_048_576:
            selected = 2
            reason = "lote intermediário: duas partições contíguas"
        else:
            selected = 4
            reason = "lote amplo: quatro partições contíguas"
    else:
        selected = int(requested)
        reason = "quantidade de workers fixada pelo experimento"
    return {
        "protocol": "casulo-training-scheduler/0.1",
        "requested_workers": requested,
        "selected_workers": selected,
        "work_per_epoch": work_per_epoch,
        "reason": reason,
        "partitions": "contiguous",
        "reduction_order": "worker-index",
        "bounded_workers": [1, 2, 4],
    }


def _pytorch_trainer(
    spec: TrainingSpec,
    dataset: TrainingDataset,
    initial: Any,
    workers: int,
) -> tuple[Callable[[], TrainingOutcome], dict[str, Any]]:
    try:
        import torch
    except ImportError as error:
        raise TrainingError(
            "PyTorch é obrigatório para o baseline: instale casulo[ml]"
        ) from error
    torch.set_num_threads(workers)
    x = torch.from_numpy(dataset.inputs)
    y = torch.from_numpy(dataset.targets)
    validation_x = torch.from_numpy(dataset.validation_inputs)
    validation_y = torch.from_numpy(dataset.validation_targets)
    f = spec.input_features
    h = spec.hidden_features
    p0 = f * h
    p1 = p0 + h
    p2 = p1 + h

    def train() -> TrainingOutcome:
        w1 = torch.tensor(
            initial[:p0].reshape(f, h),
            dtype=torch.float64,
            requires_grad=True,
        )
        b1 = torch.tensor(
            initial[p0:p1],
            dtype=torch.float64,
            requires_grad=True,
        )
        w2 = torch.tensor(
            initial[p1:p2],
            dtype=torch.float64,
            requires_grad=True,
        )
        b2 = torch.tensor(
            initial[p2],
            dtype=torch.float64,
            requires_grad=True,
        )
        parameters = (w1, b1, w2, b2)
        optimizer = torch.optim.SGD(parameters, lr=spec.learning_rate)

        def forward():
            hidden = x.matmul(w1) + b1
            hidden = (
                torch.tanh(hidden)
                if spec.activation == "tanh"
                else torch.relu(hidden)
            )
            return hidden.matmul(w2) + b2

        with torch.no_grad():
            initial_loss = torch.mean((forward() - y) ** 2).item()
        for _ in range(spec.epochs):
            optimizer.zero_grad(set_to_none=True)
            prediction = forward()
            loss = torch.mean((prediction - y) ** 2)
            loss.backward()
            optimizer.step()
        with torch.no_grad():
            prediction = forward()
            final_loss = torch.mean((prediction - y) ** 2).item()
            validation_hidden = validation_x.matmul(w1) + b1
            validation_hidden = (
                torch.tanh(validation_hidden)
                if spec.activation == "tanh"
                else torch.relu(validation_hidden)
            )
            validation_prediction = validation_hidden.matmul(w2) + b2
            validation_loss = torch.mean(
                (validation_prediction - validation_y) ** 2
            ).item()
            flat = torch.cat(
                (
                    w1.reshape(-1),
                    b1,
                    w2,
                    b2.reshape(1),
                )
            ).numpy().copy()
            predicted = validation_prediction.numpy().copy()
        return TrainingOutcome(
            backend="pytorch-eager-cpu",
            initial_loss=initial_loss,
            final_loss=final_loss,
            validation_loss=validation_loss,
            parameter_sha256=_array_sha256(flat),
            prediction_sha256=_array_sha256(predicted),
            parameters=flat,
            predictions=predicted,
        )

    return train, {
        "name": "PyTorch eager CPU",
        "version": torch.__version__,
        "threads": workers,
        "dtype": "float64",
        "optimizer": "torch.optim.SGD",
        "autograd": True,
        "mkl": "MKL" in torch.__config__.show(),
        "avx2": "AVX2" in torch.__config__.show(),
        "comparison_note": (
            "baseline industrial declarado; não é Python escalar ingênuo"
        ),
    }


def _pytorch_compiled_trainer(
    spec: TrainingSpec,
    dataset: TrainingDataset,
    initial: Any,
    workers: int,
) -> tuple[Callable[[], TrainingOutcome], dict[str, Any]]:
    toolchain = prepare_pytorch_inductor_runtime()
    if toolchain["status"] == "UNAVAILABLE":
        raise TrainingError(
            f"toolchain PyTorch/Inductor indisponível: {toolchain['error']}"
        )
    try:
        import torch
    except ImportError as error:
        raise TrainingError(
            "PyTorch é obrigatório para o baseline: instale casulo[ml]"
        ) from error
    configure_pytorch_inductor(torch)
    torch.set_num_threads(workers)
    x = torch.from_numpy(dataset.inputs)
    y = torch.from_numpy(dataset.targets)
    validation_x = torch.from_numpy(dataset.validation_inputs)
    validation_y = torch.from_numpy(dataset.validation_targets)
    f = spec.input_features
    h = spec.hidden_features
    p0 = f * h
    p1 = p0 + h
    p2 = p1 + h

    class CompiledSurrogate(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.w1 = torch.nn.Parameter(
                torch.empty((f, h), dtype=torch.float64)
            )
            self.b1 = torch.nn.Parameter(torch.empty(h, dtype=torch.float64))
            self.w2 = torch.nn.Parameter(torch.empty(h, dtype=torch.float64))
            self.b2 = torch.nn.Parameter(torch.empty((), dtype=torch.float64))

        def forward(self, values: Any) -> Any:
            hidden = values.matmul(self.w1) + self.b1
            hidden = (
                torch.tanh(hidden)
                if spec.activation == "tanh"
                else torch.relu(hidden)
            )
            return hidden.matmul(self.w2) + self.b2

    model = CompiledSurrogate()
    compiled_model = torch.compile(
        model,
        backend="inductor",
        fullgraph=True,
    )
    optimizer = torch.optim.SGD(model.parameters(), lr=spec.learning_rate)

    def reset_parameters() -> None:
        with torch.no_grad():
            model.w1.copy_(
                torch.from_numpy(initial[:p0].reshape(f, h))
            )
            model.b1.copy_(torch.from_numpy(initial[p0:p1]))
            model.w2.copy_(torch.from_numpy(initial[p1:p2]))
            model.b2.copy_(torch.tensor(initial[p2], dtype=torch.float64))
        optimizer.zero_grad(set_to_none=True)

    # Force forward and backward compilation exactly once. Official timing
    # samples below are steady-state training; compilation remains visible as
    # a separate measured cost in the report.
    reset_parameters()
    compilation_started = time.perf_counter_ns()
    compilation_prediction = compiled_model(x)
    compilation_loss = torch.mean((compilation_prediction - y) ** 2)
    compilation_loss.backward()
    compilation_wall_ns = time.perf_counter_ns() - compilation_started
    reset_parameters()

    def train() -> TrainingOutcome:
        reset_parameters()

        with torch.no_grad():
            initial_loss = torch.mean((compiled_model(x) - y) ** 2).item()
        for _ in range(spec.epochs):
            optimizer.zero_grad(set_to_none=True)
            prediction = compiled_model(x)
            loss = torch.mean((prediction - y) ** 2)
            loss.backward()
            optimizer.step()
        with torch.no_grad():
            prediction = compiled_model(x)
            final_loss = torch.mean((prediction - y) ** 2).item()
            validation_prediction = compiled_model(validation_x)
            validation_loss = torch.mean(
                (validation_prediction - validation_y) ** 2
            ).item()
            flat = torch.cat(
                (
                    model.w1.reshape(-1),
                    model.b1,
                    model.w2,
                    model.b2.reshape(1),
                )
            ).numpy().copy()
            predicted = validation_prediction.numpy().copy()
        return TrainingOutcome(
            backend=PYTORCH_COMPILE_BASELINE,
            initial_loss=initial_loss,
            final_loss=final_loss,
            validation_loss=validation_loss,
            parameter_sha256=_array_sha256(flat),
            prediction_sha256=_array_sha256(predicted),
            parameters=flat,
            predictions=predicted,
        )

    return train, {
        "name": "PyTorch compile Inductor CPU",
        "version": torch.__version__,
        "threads": workers,
        "dtype": "float64",
        "optimizer": "torch.optim.SGD",
        "autograd": True,
        "compile_backend": "inductor",
        "fullgraph_forward": True,
        "toolchain": toolchain,
        "timing_scope": "steady-state-after-compile",
        "compilation_wall_ns": compilation_wall_ns,
        "compilation_in_timed_samples": False,
        "mkl": "MKL" in torch.__config__.show(),
        "avx2": "AVX2" in torch.__config__.show(),
        "comparison_note": (
            "baseline industrial compilado; custo de compilação "
            "registrado separadamente e excluído das amostras aquecidas"
        ),
    }


def _native_trainer(
    spec: TrainingSpec,
    dataset: TrainingDataset,
    initial: Any,
    build: TrainingBuild,
    workers: int,
) -> Callable[[], TrainingOutcome]:
    np = _numpy()
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(Path(build.compiler).parent))
    library = ctypes.CDLL(str(build.library))
    pointer = ctypes.POINTER(ctypes.c_double)
    library.casulo_train.argtypes = (
        pointer,
        pointer,
        ctypes.c_size_t,
        pointer,
        ctypes.c_size_t,
        ctypes.c_double,
        ctypes.c_int,
        pointer,
        pointer,
    )
    library.casulo_train.restype = ctypes.c_int
    library.casulo_predict.argtypes = (
        pointer,
        ctypes.c_size_t,
        pointer,
        pointer,
    )
    library.casulo_predict.restype = ctypes.c_int
    x_pointer = dataset.inputs.ctypes.data_as(pointer)
    y_pointer = dataset.targets.ctypes.data_as(pointer)
    validation_pointer = dataset.validation_inputs.ctypes.data_as(pointer)

    def train() -> TrainingOutcome:
        parameters = initial.copy()
        initial_loss = ctypes.c_double()
        final_loss = ctypes.c_double()
        code = library.casulo_train(
            x_pointer,
            y_pointer,
            dataset.records,
            parameters.ctypes.data_as(pointer),
            spec.epochs,
            spec.learning_rate,
            workers,
            ctypes.byref(initial_loss),
            ctypes.byref(final_loss),
        )
        if code != 0:
            raise TrainingError(f"backend nativo retornou status {code}")
        validation_records = int(dataset.validation_inputs.shape[0])
        predictions = np.empty(validation_records, dtype=np.float64)
        code = library.casulo_predict(
            validation_pointer,
            validation_records,
            parameters.ctypes.data_as(pointer),
            predictions.ctypes.data_as(pointer),
        )
        if code != 0:
            raise TrainingError(f"predição nativa retornou status {code}")
        validation_error = predictions - dataset.validation_targets
        validation_loss = float(np.mean(validation_error * validation_error))
        return TrainingOutcome(
            backend=TRAINING_BACKEND,
            initial_loss=initial_loss.value,
            final_loss=final_loss.value,
            validation_loss=validation_loss,
            parameter_sha256=_array_sha256(parameters),
            prediction_sha256=_array_sha256(predictions),
            parameters=parameters,
            predictions=predictions,
        )

    return train


def _quality_gate(
    spec: TrainingSpec,
    reference: TrainingOutcome,
    native: TrainingOutcome,
    reference_repeat: TrainingOutcome,
    native_repeat: TrainingOutcome,
) -> dict[str, Any]:
    np = _numpy()
    initial_loss_difference = abs(reference.initial_loss - native.initial_loss)
    final_loss_difference = abs(reference.final_loss - native.final_loss)
    validation_loss_difference = abs(
        reference.validation_loss - native.validation_loss
    )
    parameter_max_abs = float(
        np.max(np.abs(reference.parameters - native.parameters))
    )
    prediction_max_abs = float(
        np.max(np.abs(reference.predictions - native.predictions))
    )
    prediction_rmse = float(
        np.sqrt(np.mean((reference.predictions - native.predictions) ** 2))
    )
    deterministic_reference = (
        reference.parameter_sha256 == reference_repeat.parameter_sha256
        and reference.prediction_sha256 == reference_repeat.prediction_sha256
    )
    deterministic_native = (
        native.parameter_sha256 == native_repeat.parameter_sha256
        and native.prediction_sha256 == native_repeat.prediction_sha256
    )
    tolerance = 2e-9
    equivalent = bool(
        initial_loss_difference <= 1e-12
        and final_loss_difference <= tolerance
        and validation_loss_difference <= tolerance
        and prediction_max_abs <= 2e-8
        and parameter_max_abs <= 2e-8
        and deterministic_reference
        and deterministic_native
    )
    return {
        "protocol": "casulo-training-equivalence/0.1",
        "same_dataset": True,
        "same_initial_parameters": True,
        "same_architecture": True,
        "same_optimizer": True,
        "same_learning_rate": True,
        "same_epochs": True,
        "initial_loss_difference": initial_loss_difference,
        "final_loss_difference": final_loss_difference,
        "validation_loss_difference": validation_loss_difference,
        "parameter_max_abs_difference": parameter_max_abs,
        "prediction_max_abs_difference": prediction_max_abs,
        "prediction_rmse_difference": prediction_rmse,
        "numeric_tolerance": tolerance,
        "pytorch_deterministic": deterministic_reference,
        "casulo_t_deterministic": deterministic_native,
        "equivalent_training": equivalent,
        "quality_target": spec.target_loss,
        "pytorch_final_loss": reference.final_loss,
        "casulo_t_final_loss": native.final_loss,
        "pytorch_validation_loss": reference.validation_loss,
        "casulo_t_validation_loss": native.validation_loss,
        "pytorch_validation_r2": 1.0 - reference.validation_loss,
        "casulo_t_validation_r2": 1.0 - native.validation_loss,
        "quality_target_reached": bool(
            reference.validation_loss <= spec.target_loss
            and native.validation_loss <= spec.target_loss
        ),
    }


def _write_training_bundle(
    output: Path,
    dataset: TrainingDataset,
    report: TrainingExperimentReport,
) -> None:
    dataset_payload = {
        "protocol": TRAINING_DATASET_PROTOCOL,
        "manifest": dataset.manifest(),
        "inputs": dataset.inputs.tolist(),
        "targets": dataset.targets.tolist(),
        "validation_inputs": dataset.validation_inputs.tolist(),
        "validation_targets": dataset.validation_targets.tolist(),
    }
    (output / "dataset.json").write_text(
        json.dumps(
            dataset_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    report_payload = report.to_dict()
    (output / "training-report.json").write_text(
        json.dumps(
            report_payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "training-report.html").write_text(
        _render_training_html(report_payload),
        encoding="utf-8",
        newline="\n",
    )


def _render_training_html(report: dict[str, Any]) -> str:
    comparison = report["comparison"]
    quality = report["quality"]
    speedup = comparison["paired_speedup_median"]
    lower = comparison["paired_speedup_ci95"]["lower"]
    upper = comparison["paired_speedup_ci95"]["upper"]
    baseline_seconds = report["pytorch"]["median_wall_ns"] / 1e9
    native_seconds = report["casulo_t"]["median_wall_ns"] / 1e9
    baseline_name = report["baseline"]["name"]
    timing_scope = report["baseline"].get(
        "timing_scope",
        "end-to-end-eager",
    )
    compilation_ns = report["baseline"].get("compilation_wall_ns")
    compilation_seconds = (
        float(compilation_ns) / 1e9 if compilation_ns is not None else None
    )
    projected_minutes = 360.0 / speedup
    time_reduction = 100.0 * (1.0 - 1.0 / speedup)
    gate = comparison["claim_gate_6x"]
    payload = json.dumps(
        report,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Casulo — treinamento científico</title>
<style>
:root{{--bg:#080a0d;--panel:#12161b;--ink:#f4f3ed;--muted:#9ca3ad;--lime:#b8f34a;--line:#29313a;--red:#ff7d73}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 75% 0,#1a2614,transparent 38rem),var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}}
main{{width:min(1100px,calc(100% - 32px));margin:auto;padding:64px 0}}header{{padding:48px 0 64px}}.tag{{color:var(--lime);font-size:.75rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase}}
h1{{font-size:clamp(3rem,8vw,7rem);line-height:.9;letter-spacing:-.07em;margin:20px 0}}h1 span{{color:var(--lime)}}.lead{{max-width:720px;color:#c7cbd0;font-size:1.15rem}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}}.card{{background:rgba(18,22,27,.9);border:1px solid var(--line);border-radius:22px;padding:28px}}.metric strong{{display:block;font-size:2.5rem;letter-spacing:-.05em}}.metric span{{color:var(--muted)}}h2{{margin-top:70px;font-size:2.4rem;letter-spacing:-.04em}}
.bar{{height:18px;background:#20262d;border-radius:99px;overflow:hidden;margin:12px 0 24px}}.fill{{height:100%;border-radius:99px}}.torch{{width:100%;background:#6f7884}}.casulo{{width:{min(100.0, 100.0 / max(speedup, .001)):.3f}%;background:var(--lime)}}code{{font-family:Consolas,monospace;color:#d7edaa}}.ok{{color:var(--lime)}}.fail{{color:var(--red)}}ul{{padding-left:20px;color:#c9ccd0}}footer{{margin-top:70px;padding-top:24px;border-top:1px solid var(--line);color:var(--muted);font-size:.8rem}}
@media(max-width:700px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body><main>
<header><div class="tag">Casulo · Teloscorp · prova de treinamento</div>
<h1>Treino completo em <span>{speedup:.2f}×</span> da velocidade.</h1>
<p class="lead">MLP hidrológica, mesma entrada, inicialização, arquitetura, SGD, épocas e qualidade numérica. {baseline_name} contra linguagem T compilada e fundida em C99/OpenMP.</p>
</header>
<div class="grid">
<section class="card metric"><span>{baseline_name}</span><strong>{baseline_seconds:.4f}s</strong><span>mediana · {timing_scope}</span></section>
<section class="card metric"><span>Casulo + T</span><strong>{native_seconds:.4f}s</strong><span>mediana ponta a ponta</span></section>
<section class="card metric"><span>Ganho pareado</span><strong>{speedup:.4f}×</strong><span>IC95% {lower:.4f}×–{upper:.4f}×</span></section>
<section class="card metric"><span>Gate comercial 6×</span><strong class="{'ok' if gate else 'fail'}">{'APROVADO' if gate else 'NÃO APROVADO'}</strong><span>{comparison['claim']}</span></section>
</div>
<h2>Se X fosse 6 horas</h2>
<div class="grid">
<section class="card metric"><span>Baseline hipotético</span><strong>6h 00min</strong><span>mesma carga e mesmas condições do experimento</span></section>
<section class="card metric"><span>Casulo/T projetado</span><strong>{int(projected_minutes)}min {int((projected_minutes % 1) * 60):02d}s</strong><span>{time_reduction:.2f}% do tempo liberado</span></section>
</div>
{f'<p class="lead">Compilação inicial do baseline: {compilation_seconds:.4f}s, registrada separadamente e não incluída nas amostras aquecidas.</p>' if compilation_seconds is not None else ''}
<p class="lead">Esta tradução é uma projeção linear para tornar a escala compreensível; o treinamento efetivamente cronometrado levou milissegundos. Uma alegação de horas literais exige executar uma carga longa equivalente.</p>
<h2>Mesma carga, escala visual</h2>
<section class="card"><strong>{baseline_name}</strong><div class="bar"><div class="fill torch"></div></div>
<strong>Casulo/T C99 fundido</strong><div class="bar"><div class="fill casulo"></div></div></section>
<h2>Gate de equivalência</h2>
<section class="card"><ul>
<li>Treinamento equivalente: <strong class="{'ok' if quality['equivalent_training'] else 'fail'}">{str(quality['equivalent_training']).lower()}</strong></li>
<li>Meta de qualidade: <strong class="{'ok' if quality['quality_target_reached'] else 'fail'}">{str(quality['quality_target_reached']).lower()}</strong></li>
<li>Loss PyTorch: <code>{quality['pytorch_final_loss']:.12g}</code></li>
<li>Loss Casulo/T: <code>{quality['casulo_t_final_loss']:.12g}</code></li>
<li>Loss de validação PyTorch: <code>{quality['pytorch_validation_loss']:.12g}</code></li>
<li>Loss de validação Casulo/T: <code>{quality['casulo_t_validation_loss']:.12g}</code></li>
<li>R² de validação: <code>{quality['casulo_t_validation_r2']:.6f}</code></li>
<li>Forma da rede: <code>8 → 8 ReLU → 1; 400 épocas</code></li>
<li>Scheduler Crisálida: <code>{comparison['scheduler']['selected_workers']} worker</code> — {comparison['scheduler']['reason']}</li>
<li>Diferença RMSE das predições: <code>{quality['prediction_rmse_difference']:.3e}</code></li>
<li>Energia elétrica: <code>não medida</code></li>
</ul></section>
<h2>Escopo honesto</h2>
<section class="card"><p>Este relatório mede um treinamento full-batch em memória. Não afirma o mesmo ganho para qualquer rede, GPU, arquitetura, dataset ou pipeline. O número de 6× só é liberado quando o limite inferior do IC95% é pelo menos 6× e todos os gates de qualidade são aprovados.</p></section>
<footer>Casulo é um invento original da Teloscorp para Otimização de Tráfego de Informação.</footer>
<script id="training-evidence" type="application/json">{payload}</script>
</main></body></html>
"""


def _render_training_c(spec: LearnNativePlan, artifact_id: str) -> str:
    activation = (
        "tanh(value)"
        if spec.activation == "tanh"
        else "(value > 0.0 ? value : 0.0)"
    )
    derivative = (
        "(1.0 - hidden * hidden)"
        if spec.activation == "tanh"
        else "(value > 0.0 ? 1.0 : 0.0)"
    )
    return f"""#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#ifdef _OPENMP
#include <omp.h>
#endif
#if defined(_WIN32)
#define CASULO_EXPORT __declspec(dllexport)
#else
#define CASULO_EXPORT __attribute__((visibility("default")))
#endif
#define INPUTS {spec.input_features}u
#define HIDDEN {spec.hidden_features}u
#define PARAMS (INPUTS * HIDDEN + HIDDEN + HIDDEN + 1u)

static double activate(double value) {{ return {activation}; }}
static double derivative(double value, double hidden) {{
    (void)hidden;
    return {derivative};
}}
static double predict_one(const double *x, const double *p) {{
    const size_t b1 = INPUTS * HIDDEN;
    const size_t w2 = b1 + HIDDEN;
    const size_t b2 = w2 + HIDDEN;
    double values[HIDDEN];
    double output = p[b2];
    size_t j, k;
    for (j = 0u; j < HIDDEN; ++j) {{
        values[j] = p[b1 + j];
    }}
    for (k = 0u; k < INPUTS; ++k) {{
        const double input = x[k];
        for (j = 0u; j < HIDDEN; ++j) {{
            values[j] += input * p[k * HIDDEN + j];
        }}
    }}
    for (j = 0u; j < HIDDEN; ++j) {{
        output += activate(values[j]) * p[w2 + j];
    }}
    return output;
}}
static double evaluate_loss(
    const double *x,
    const double *y,
    size_t records,
    const double *p
) {{
    double loss = 0.0;
    size_t i;
    for (i = 0u; i < records; ++i) {{
        const double error = predict_one(x + i * INPUTS, p) - y[i];
        loss += error * error;
    }}
    return loss / (double)records;
}}
CASULO_EXPORT const char *casulo_training_artifact(void) {{
    return "{artifact_id}";
}}
CASULO_EXPORT size_t casulo_parameter_count(void) {{ return PARAMS; }}
CASULO_EXPORT int casulo_train(
    const double *x,
    const double *y,
    size_t records,
    double *p,
    size_t epochs,
    double learning_rate,
    int requested_workers,
    double *initial_loss,
    double *final_loss
) {{
    double *gradients;
    int workers = requested_workers;
    if (!x || !y || !p || !initial_loss || !final_loss ||
        records == 0u || epochs == 0u || learning_rate <= 0.0 ||
        workers < 1 || workers > 4) {{
        return -1;
    }}
#ifndef _OPENMP
    workers = 1;
#endif
    gradients = (double *)calloc((size_t)workers * (PARAMS + 1u), sizeof(double));
    if (!gradients) return -2;
    *initial_loss = evaluate_loss(x, y, records, p);
    {{
        size_t epoch;
        for (epoch = 0u; epoch < epochs; ++epoch) {{
            size_t q;
            memset(
                gradients,
                0,
                (size_t)workers * (PARAMS + 1u) * sizeof(double)
            );
#ifdef _OPENMP
#pragma omp parallel num_threads(workers)
#endif
            {{
                int thread_id = 0;
                int team_size = 1;
                size_t start, end, i, j, k;
                double *g;
#ifdef _OPENMP
                thread_id = omp_get_thread_num();
                team_size = omp_get_num_threads();
#endif
                start = records * (size_t)thread_id / (size_t)team_size;
                end = records * (size_t)(thread_id + 1) / (size_t)team_size;
                g = gradients + (size_t)thread_id * (PARAMS + 1u);
                for (i = start; i < end; ++i) {{
                    const double *row = x + i * INPUTS;
                    double hidden_values[HIDDEN];
                    double preactivation[HIDDEN];
                    double delta[HIDDEN];
                    double prediction = p[INPUTS * HIDDEN + HIDDEN + HIDDEN];
                    const double scale = 2.0 / (double)records;
                    for (j = 0u; j < HIDDEN; ++j) {{
                        preactivation[j] = p[INPUTS * HIDDEN + j];
                    }}
                    for (k = 0u; k < INPUTS; ++k) {{
                        const double input = row[k];
                        for (j = 0u; j < HIDDEN; ++j) {{
                            preactivation[j] +=
                                input * p[k * HIDDEN + j];
                        }}
                    }}
                    for (j = 0u; j < HIDDEN; ++j) {{
                        hidden_values[j] = activate(preactivation[j]);
                        prediction += hidden_values[j] *
                            p[INPUTS * HIDDEN + HIDDEN + j];
                    }}
                    {{
                        const double error = prediction - y[i];
                        const double output_gradient = scale * error;
                        g[PARAMS] += error * error;
                        g[INPUTS * HIDDEN + HIDDEN + HIDDEN] += output_gradient;
                        for (j = 0u; j < HIDDEN; ++j) {{
                            const double dz = output_gradient *
                                p[INPUTS * HIDDEN + HIDDEN + j] *
                                derivative(
                                    preactivation[j],
                                    hidden_values[j]
                                );
                            delta[j] = dz;
                            g[INPUTS * HIDDEN + HIDDEN + j] +=
                                output_gradient * hidden_values[j];
                            g[INPUTS * HIDDEN + j] += dz;
                        }}
                        for (k = 0u; k < INPUTS; ++k) {{
                            const double input = row[k];
                            for (j = 0u; j < HIDDEN; ++j) {{
                                g[k * HIDDEN + j] += delta[j] * input;
                            }}
                        }}
                    }}
                }}
            }}
            for (q = 0u; q < PARAMS; ++q) {{
                size_t worker;
                double total = 0.0;
                for (worker = 0u; worker < (size_t)workers; ++worker) {{
                    total += gradients[worker * (PARAMS + 1u) + q];
                }}
                p[q] -= learning_rate * total;
            }}
        }}
    }}
    *final_loss = evaluate_loss(x, y, records, p);
    free(gradients);
    return 0;
}}
CASULO_EXPORT int casulo_predict(
    const double *x,
    size_t records,
    const double *p,
    double *predictions
) {{
    size_t i;
    if (!x || !p || !predictions) return -1;
    for (i = 0u; i < records; ++i) {{
        predictions[i] = predict_one(x + i * INPUTS, p);
    }}
    return 0;
}}
"""


def _outcome_summary(outcome: TrainingOutcome) -> dict[str, Any]:
    return {
        "backend": outcome.backend,
        "initial_loss": outcome.initial_loss,
        "final_loss": outcome.final_loss,
        "validation_loss": outcome.validation_loss,
        "parameter_sha256": outcome.parameter_sha256,
        "prediction_sha256": outcome.prediction_sha256,
    }


def _measure_once(
    function: Callable[[], TrainingOutcome],
) -> tuple[int, int]:
    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    function()
    cpu = time.process_time_ns() - cpu_start
    wall = time.perf_counter_ns() - wall_start
    return wall, cpu


def _training_measurement(
    name: str,
    wall: list[int],
    cpu: list[int],
) -> TrainingMeasurement:
    return TrainingMeasurement(
        name=name,
        samples=len(wall),
        wall_ns_samples=tuple(wall),
        cpu_ns_samples=tuple(cpu),
        median_wall_ns=int(statistics.median(wall)),
        median_cpu_ns=int(statistics.median(cpu)),
    )


def _bootstrap_median_ci(
    values: tuple[float, ...],
    *,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    if not values:
        raise TrainingError("intervalo exige amostras pareadas")
    generator = random.Random(seed)
    size = len(values)
    medians = sorted(
        statistics.median(
            values[generator.randrange(size)]
            for _ in range(size)
        )
        for _ in range(resamples)
    )
    return {
        "lower": medians[int(0.025 * (resamples - 1))],
        "upper": medians[int(0.975 * (resamples - 1))],
        "confidence": 0.95,
        "method": "paired-bootstrap-median",
        "resamples": resamples,
        "seed": seed,
    }


def _numpy():
    try:
        import numpy as np
    except ImportError as error:
        raise TrainingError(
            "NumPy é obrigatório: instale casulo[ml]"
        ) from error
    return np


def _array_sha256(array: Any) -> str:
    contiguous = _numpy().ascontiguousarray(array, dtype=_numpy().float64)
    return _sha256(contiguous.tobytes(order="C"))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
