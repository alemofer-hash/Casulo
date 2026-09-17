from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .adaptativo import AdaptiveError, run_adaptive_artifact
from .api import check_file
from .autograd import (
    AutogradError,
    check_gradients_file,
    compile_autograd_file,
)
from .artifact import (
    ArtifactBuilder,
    ArtifactError,
    CompilationFailed,
)
from .ast import ast_to_dict
from .backend import BackendError
from .benchmark import BenchmarkError, benchmark_artifact
from .borboleta import (
    BorboletaConfig,
    BorboletaError,
    BorboletaLaboratorio,
    generate_hydrological_dataset,
)
from .causal_profiler import (
    CausalProfilerError,
    create_causal_profile,
)
from .learn_native import LearnNativeError, build_learn_tcap
from .native import NativeError, compile_native_artifact, run_native_artifact
from .native_benchmark import (
    NativeBenchmarkError,
    benchmark_native_artifact,
)
from .parity import (
    ParityError,
    ParityStatus,
    execute_numpy_file,
    run_pytorch_parity_file,
)
from .pytorch_runtime import probe_pytorch_runtime
from .runner import ExecutionFailed, run_artifact
from .scientific import (
    PYTORCH_COMPILE_BASELINE,
    PYTORCH_EAGER_BASELINE,
    ScientificError,
    create_training_preregistration,
    judge_training_evidence,
    probe_pytorch_compile,
    verify_scientific_chain,
)
from .simd_benchmark import SimdBenchmarkError, benchmark_simd_artifact
from .tensor import TensorError, compile_tensor_file
from .tensor_cpu import (
    DEFAULT_ARENA_BUDGET_BYTES,
    TensorCpuError,
    execute_tensor_cpu_file,
    plan_tensor_cpu,
)
from .tensor_lab import (
    TENSOR_LAB_BACKEND_EAGER,
    TENSOR_LAB_BACKEND_INDUCTOR,
    TensorLabError,
    create_tensor_lab_preregistration,
    judge_tensor_lab,
    run_tensor_lab,
    verify_tensor_lab_chain,
)
from .tensor_suite import (
    TensorSuiteError,
    create_tensor_suite_preregistration,
    judge_tensor_suite,
    run_tensor_suite,
    verify_tensor_suite_chain,
)
from .training import TrainingError, run_training_experiment
from .workspace import (
    WORKSPACE_MANIFEST,
    WorkspaceError,
    build_workspace,
    check_workspace,
    init_workspace,
    resolve_entry_source,
    test_workspace,
)


LEGACY_RESEARCH_ENV = "CASULO_ENABLE_LEGACY_RESEARCH"
LEGACY_RESEARCH_COMMANDS = frozenset(
    {
        "benchmark",
        "native-benchmark",
        "simd-benchmark",
        "experiment",
        "training-experiment",
        "scientific-preregister",
        "scientific-probe",
        "scientific-judge",
        "scientific-verify",
        "pytorch-doctor",
        "pytorch-parity",
        "tensor-lab-preregister",
        "tensor-lab-run",
        "tensor-lab-judge",
        "tensor-lab-verify",
        "tensor-suite-preregister",
        "tensor-suite-run",
        "tensor-suite-judge",
        "tensor-suite-verify",
        "tensor-causal-profile",
    }
)


def _legacy_research_enabled() -> bool:
    return os.environ.get(LEGACY_RESEARCH_ENV, "").strip() == "1"


def _guard_legacy_research(command: str) -> None:
    if command not in LEGACY_RESEARCH_COMMANDS or _legacy_research_enabled():
        return
    raise SystemExit(
        "t: comando de pesquisa histórica bloqueado no perfil de produto. "
        f"Para reprodução deliberada, defina {LEGACY_RESEARCH_ENV}=1. "
        "O opt-in não torna o resultado um gate ou claim do produto."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="t",
        description="Compilador aberto da linguagem T para o Casulo.",
    )
    parser.add_argument("--version", action="version", version=f"T {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init",
        help="Cria o esqueleto de um projeto T.",
    )
    init.add_argument("target", type=Path)
    init.add_argument("--name")

    check = commands.add_parser("check", help="Verifica sintaxe e semântica.")
    check.add_argument("source", type=Path)
    check.add_argument("--format", choices=("text", "json"), default="text")

    inspect = commands.add_parser(
        "inspect",
        help="Exibe AST, símbolos ou CrisálidaIR.",
    )
    inspect.add_argument("source", type=Path)
    mode = inspect.add_mutually_exclusive_group()
    mode.add_argument("--ast", action="store_true", help="Exibe a AST.")
    mode.add_argument(
        "--symbols",
        action="store_true",
        help="Exibe a tabela de símbolos.",
    )
    mode.add_argument(
        "--ir",
        action="store_true",
        help="Exibe a CrisálidaIR.",
    )
    mode.add_argument(
        "--graph",
        action="store_true",
        help="Exibe o grafo def-use da Metamorfose.",
    )
    inspect.add_argument("--format", choices=("json", "text"))

    build = commands.add_parser(
        "build",
        help="Compila uma fonte ou um projeto T reproduzível.",
    )
    build.add_argument("source", type=Path)
    build.add_argument("--output", type=Path)
    build.add_argument("--native", action="store_true")
    build.add_argument("--format", choices=("text", "json"), default="text")

    run = commands.add_parser(
        "run",
        help="Executa uma fonte T ou um artefato Crisálida.",
    )
    run.add_argument("target", type=Path)
    run.add_argument("--operation")
    run.add_argument(
        "--batch",
        action="store_true",
        help="Exige uma lista JSON e executa o kernel de lote.",
    )
    run.add_argument(
        "--no-cache",
        action="store_true",
        help="Desativa memoização por operação nesta execução.",
    )
    run.add_argument(
        "--adaptive",
        action="store_true",
        help="A Crisálida escolhe recalcular ou deduplicar o lote.",
    )
    run.add_argument("--native", action="store_true")
    run.add_argument("--native-required", action="store_true")
    run.add_argument(
        "--memory-budget-mb",
        type=int,
        default=64,
        help="Orçamento de cache para a decisão adaptativa.",
    )
    payload = run.add_mutually_exclusive_group()
    payload.add_argument(
        "--input",
        help="Arquivo JSON de entrada; use - para stdin.",
    )
    payload.add_argument("--data", help="Objeto JSON informado na linha de comando.")
    run.add_argument(
        "--build-dir",
        type=Path,
        help="Destino do build implícito quando target é uma fonte .t.",
    )
    run.add_argument("--format", choices=("json", "text"), default="json")

    test = commands.add_parser(
        "test",
        help="Valida módulos e testes de um projeto T.",
    )
    test.add_argument("target", type=Path)
    test.add_argument("--format", choices=("text", "json"), default="text")

    benchmark = commands.add_parser(
        "benchmark",
        help="Compara execução escalar e lote fundido.",
    )
    benchmark.add_argument("target", type=Path)
    benchmark.add_argument("--operation")
    benchmark_input = benchmark.add_mutually_exclusive_group(required=True)
    benchmark_input.add_argument("--input")
    benchmark_input.add_argument("--data")
    benchmark.add_argument("--repeat", type=int, default=1)
    benchmark.add_argument("--samples", type=int, default=5)
    benchmark.add_argument("--iterations", type=int, default=10)
    benchmark.add_argument("--output", type=Path)
    benchmark.add_argument("--build-dir", type=Path)

    native_benchmark = commands.add_parser(
        "native-benchmark",
        help="Compara Python escalar e o artefato C99.",
    )
    native_benchmark.add_argument("target", type=Path)
    native_benchmark.add_argument("--operation")
    native_input = native_benchmark.add_mutually_exclusive_group(required=True)
    native_input.add_argument("--input")
    native_input.add_argument("--data")
    native_benchmark.add_argument("--repeat", type=int, default=1)
    native_benchmark.add_argument("--samples", type=int, default=7)
    native_benchmark.add_argument("--iterations", type=int, default=5)
    native_benchmark.add_argument("--output", type=Path)
    native_benchmark.add_argument("--build-dir", type=Path)

    simd_benchmark = commands.add_parser(
        "simd-benchmark",
        help="Compara o kernel C99 escalar estrito com SIMD da máquina.",
    )
    simd_benchmark.add_argument("target", type=Path)
    simd_benchmark.add_argument("--operation")
    simd_input = simd_benchmark.add_mutually_exclusive_group(required=True)
    simd_input.add_argument("--input")
    simd_input.add_argument("--data")
    simd_benchmark.add_argument("--repeat", type=int, default=1)
    simd_benchmark.add_argument("--samples", type=int, default=9)
    simd_benchmark.add_argument("--iterations", type=int, default=2_000)
    simd_benchmark.add_argument("--output", type=Path)
    simd_benchmark.add_argument("--build-dir", type=Path)

    experiment = commands.add_parser(
        "experiment",
        help="Produz evidência Borboleta reproduzível em JSON e HTML.",
    )
    experiment.add_argument("target", type=Path)
    experiment.add_argument("--operation")
    experiment.add_argument("--output", type=Path, required=True)
    experiment.add_argument("--records", type=int, default=2_000)
    experiment.add_argument("--samples", type=int, default=9)
    experiment.add_argument("--iterations", type=int, default=5)
    experiment.add_argument("--warmups", type=int, default=2)
    experiment.add_argument("--seed", type=int, default=24_052_024)
    experiment.add_argument("--duplicate-rate", type=float, default=0.35)
    experiment.add_argument("--bootstrap-resamples", type=int, default=2_000)
    experiment.add_argument("--build-dir", type=Path)

    training = commands.add_parser(
        "training-experiment",
        help="Compara treinamento PyTorch e T/C99 com prova de qualidade.",
    )
    training.add_argument("source", type=Path)
    training.add_argument("--output", type=Path, required=True)
    training.add_argument("--records", type=int, default=1_024)
    training.add_argument("--samples", type=int, default=9)
    training.add_argument("--warmups", type=int, default=2)
    training.add_argument(
        "--workers",
        choices=("auto", "1", "2", "4"),
        default="auto",
    )

    tcap_build = commands.add_parser(
        "tcap-build",
        help="Baixa learn pelo IR/grafo geral e gera payload nativo .tcap.",
    )
    tcap_build.add_argument("source", type=Path)
    tcap_build.add_argument("--output", type=Path, required=True)
    training.add_argument("--seed", type=int, default=20_260_730)
    training.add_argument("--bootstrap-resamples", type=int, default=2_000)
    training.add_argument(
        "--baseline",
        choices=(PYTORCH_EAGER_BASELINE, PYTORCH_COMPILE_BASELINE),
        default=PYTORCH_EAGER_BASELINE,
        help="Baseline PyTorch medido nesta execução.",
    )
    training.add_argument(
        "--preregistration",
        type=Path,
        help="Pré-registro selado; sem ele a execução é exploratória e não libera claims.",
    )

    preregister = commands.add_parser(
        "scientific-preregister",
        help="Sela hipótese, desenho, baselines e gates antes da medição.",
    )
    preregister.add_argument("source", type=Path)
    preregister.add_argument("--output", type=Path, required=True)
    preregister.add_argument("--records", type=int, default=1_024)
    preregister.add_argument("--samples", type=int, default=21)
    preregister.add_argument("--warmups", type=int, default=3)
    preregister.add_argument(
        "--workers",
        choices=("auto", "1", "2", "4"),
        default="auto",
    )
    preregister.add_argument("--seed", type=int, default=20_260_730)
    preregister.add_argument("--bootstrap-resamples", type=int, default=2_000)
    preregister.add_argument(
        "--baseline",
        action="append",
        choices=(PYTORCH_EAGER_BASELINE, PYTORCH_COMPILE_BASELINE),
        dest="baselines",
    )
    preregister.add_argument(
        "--superiority-threshold",
        type=float,
        default=1.0,
    )
    preregister.add_argument(
        "--commercial-threshold",
        type=float,
        default=6.0,
    )

    probe = commands.add_parser(
        "scientific-probe",
        help="Registra, sem omitir falhas, a disponibilidade do torch.compile.",
    )
    probe.add_argument("--output", type=Path, required=True)

    judge = commands.add_parser(
        "scientific-judge",
        help="Recalcula a evidência e emite veredito imutável.",
    )
    judge.add_argument("--preregistration", type=Path, required=True)
    judge.add_argument("--report", type=Path, required=True)
    judge.add_argument("--output", type=Path, required=True)

    verify_scientific = commands.add_parser(
        "scientific-verify",
        help="Reproduz selos, métricas, classificação e cadeia de custódia.",
    )
    verify_scientific.add_argument("--preregistration", type=Path, required=True)
    verify_scientific.add_argument("--report", type=Path, required=True)
    verify_scientific.add_argument("--probe", type=Path, required=True)
    verify_scientific.add_argument("--verdict", type=Path, required=True)

    tensor_compile = commands.add_parser(
        "tensor-compile",
        help="Verifica e baixa um grafo tensorial declarativo para TensorIR.",
    )
    tensor_compile.add_argument("source", type=Path)
    tensor_compile.add_argument("--output", type=Path)
    tensor_compile.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )

    autograd_compile = commands.add_parser(
        "autograd-compile",
        help="Forma um backward explícito e versionado sobre a TensorIR.",
    )
    autograd_compile.add_argument("source", type=Path)
    autograd_compile.add_argument("--wrt", nargs="+", required=True)
    autograd_compile.add_argument("--loss")
    autograd_compile.add_argument("--output", type=Path)
    autograd_compile.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )

    gradient_check = commands.add_parser(
        "autograd-check",
        help="Compara o backward analítico com diferenças finitas.",
    )
    gradient_check.add_argument("source", type=Path)
    gradient_check.add_argument("--input", type=Path, required=True)
    gradient_check.add_argument("--wrt", nargs="+", required=True)
    gradient_check.add_argument("--loss")
    gradient_check.add_argument("--epsilon", type=float, default=1e-6)
    gradient_check.add_argument(
        "--absolute-tolerance",
        type=float,
        default=1e-6,
    )
    gradient_check.add_argument(
        "--relative-tolerance",
        type=float,
        default=1e-5,
    )
    gradient_check.add_argument("--max-elements", type=int, default=4_096)

    numpy_execute = commands.add_parser(
        "numpy-execute",
        help="Executa forward e backward da IR no backend NumPy de referência.",
    )
    numpy_execute.add_argument("source", type=Path)
    numpy_execute.add_argument("--input", type=Path, required=True)
    numpy_execute.add_argument("--wrt", nargs="+", required=True)
    numpy_execute.add_argument("--loss")
    numpy_execute.add_argument("--output", type=Path)
    numpy_execute.add_argument("--summary-only", action="store_true")

    pytorch_parity = commands.add_parser(
        "pytorch-parity",
        help="Compara intermediários, loss e gradientes com PyTorch CPU.",
    )
    pytorch_parity.add_argument("source", type=Path)
    pytorch_parity.add_argument("--input", type=Path, required=True)
    pytorch_parity.add_argument("--wrt", nargs="+", required=True)
    pytorch_parity.add_argument("--loss")
    pytorch_parity.add_argument("--output", type=Path)

    tensor_cpu_plan = commands.add_parser(
        "tensor-cpu-plan",
        help="Forma fusão, arena e scheduler do backend CPU tensorial.",
    )
    tensor_cpu_plan.add_argument("source", type=Path)
    tensor_cpu_plan.add_argument("--wrt", nargs="+", required=True)
    tensor_cpu_plan.add_argument("--loss")
    tensor_cpu_plan.add_argument(
        "--arena-budget",
        type=int,
        default=DEFAULT_ARENA_BUDGET_BYTES,
    )
    tensor_cpu_plan.add_argument(
        "--workers",
        choices=("auto", "1", "2", "4"),
        default="auto",
    )
    tensor_cpu_plan.add_argument(
        "--gemm-workers",
        choices=("adaptive", "1", "2", "4"),
    )
    tensor_cpu_plan.add_argument(
        "--provider",
        choices=("owned", "openblas"),
        default="owned",
    )
    tensor_cpu_plan.add_argument("--output", type=Path)

    causal_profile = commands.add_parser(
        "tensor-causal-profile",
        help=(
            "Expõe FLOPs, tráfego, materializações e ablações sem "
            "cronometrar."
        ),
    )
    causal_profile.add_argument("source", type=Path)
    causal_profile.add_argument("--output", type=Path, required=True)
    causal_profile.add_argument("--wrt", nargs="+", required=True)
    causal_profile.add_argument("--loss")
    causal_profile.add_argument(
        "--arena-budget",
        type=int,
        default=DEFAULT_ARENA_BUDGET_BYTES,
    )
    causal_profile.add_argument(
        "--workers",
        choices=("auto", "1", "2", "4"),
        default="auto",
    )
    causal_profile.add_argument(
        "--gemm-workers",
        choices=("adaptive", "1", "2", "4"),
    )
    causal_profile.add_argument(
        "--provider",
        choices=("owned", "openblas"),
        default="owned",
    )

    tensor_cpu_run = commands.add_parser(
        "tensor-cpu-run",
        help="Executa forward/backward C99 e julga contra NumPy/PyTorch.",
    )
    tensor_cpu_run.add_argument("source", type=Path)
    tensor_cpu_run.add_argument("--input", type=Path, required=True)
    tensor_cpu_run.add_argument("--wrt", nargs="+", required=True)
    tensor_cpu_run.add_argument("--loss")
    tensor_cpu_run.add_argument(
        "--arena-budget",
        type=int,
        default=DEFAULT_ARENA_BUDGET_BYTES,
    )
    tensor_cpu_run.add_argument(
        "--workers",
        choices=("auto", "1", "2", "4"),
        default="auto",
    )
    tensor_cpu_run.add_argument(
        "--gemm-workers",
        choices=("adaptive", "1", "2", "4"),
    )
    tensor_cpu_run.add_argument(
        "--provider",
        choices=("owned", "openblas"),
        default="owned",
    )
    tensor_cpu_run.add_argument("--no-fallback", action="store_true")
    tensor_cpu_run.add_argument("--output", type=Path)

    tensor_lab_preregister = commands.add_parser(
        "tensor-lab-preregister",
        help="Sela o laboratório Casulo/T versus PyTorch antes da medição.",
    )
    tensor_lab_preregister.add_argument("source", type=Path)
    tensor_lab_preregister.add_argument("--output", type=Path, required=True)
    tensor_lab_preregister.add_argument("--wrt", nargs="+", required=True)
    tensor_lab_preregister.add_argument("--loss")
    tensor_lab_preregister.add_argument("--samples", type=int, default=21)
    tensor_lab_preregister.add_argument("--warmups", type=int, default=3)
    tensor_lab_preregister.add_argument(
        "--inner-iterations",
        type=int,
        default=100,
    )
    tensor_lab_preregister.add_argument(
        "--target-sample-ms",
        type=float,
        default=250.0,
        help=(
            "Duração mínima de cada lote por backend; calibração ocorre antes "
            "das amostras e não observa speedup."
        ),
    )
    tensor_lab_preregister.add_argument(
        "--maximum-inner-iterations",
        type=int,
        default=1_000_000,
    )
    tensor_lab_preregister.add_argument(
        "--cooldown-ms",
        type=int,
        default=0,
    )
    tensor_lab_preregister.add_argument(
        "--cpu-affinity",
        nargs="+",
        type=int,
        help="Índices lógicos de CPU selados para o processo inteiro.",
    )
    tensor_lab_preregister.add_argument(
        "--max-cv",
        type=float,
        default=0.15,
        help=(
            "Coeficiente de variação máximo; acima dele o Juiz retorna "
            "INCONCLUSIVE."
        ),
    )
    tensor_lab_preregister.add_argument(
        "--workers",
        choices=("1", "2", "4"),
        default="1",
    )
    tensor_lab_preregister.add_argument(
        "--gemm-workers",
        choices=("1", "2", "4"),
        help=(
            "Threads internas do GEMM; precisam caber no orçamento de workers."
        ),
    )
    tensor_lab_preregister.add_argument(
        "--provider",
        choices=("owned", "openblas"),
        default="owned",
        help="Provedor GEMM a ser descoberto, selado e auditado.",
    )
    tensor_lab_preregister.add_argument(
        "--seed",
        type=int,
        default=20_260_730,
    )
    tensor_lab_preregister.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=2_000,
    )
    tensor_lab_preregister.add_argument(
        "--arena-budget",
        type=int,
        default=DEFAULT_ARENA_BUDGET_BYTES,
    )
    tensor_lab_preregister.add_argument(
        "--baseline",
        action="append",
        choices=(
            TENSOR_LAB_BACKEND_EAGER,
            TENSOR_LAB_BACKEND_INDUCTOR,
        ),
        dest="tensor_lab_baselines",
    )
    tensor_lab_preregister.add_argument(
        "--superiority-threshold",
        type=float,
        default=1.0,
    )
    tensor_lab_preregister.add_argument(
        "--commercial-threshold",
        type=float,
        default=6.0,
    )
    tensor_lab_preregister.add_argument(
        "--prior-exploratory-disclosure",
        help="Declara toda observação exploratória relevante anterior.",
    )
    tensor_lab_preregister.add_argument(
        "--prior-same-design-observed",
        action="store_true",
        help=(
            "Marca que este mesmo desenho já foi observado; a execução "
            "será uma replicação confirmatória."
        ),
    )
    tensor_lab_preregister.add_argument(
        "--claim-ineligible",
        action="store_true",
        help=(
            "Sela smoke test ou exploração: mede e classifica, mas o Juiz "
            "não libera claim nem gate comercial."
        ),
    )

    tensor_lab_run = commands.add_parser(
        "tensor-lab-run",
        help="Executa exatamente o laboratório tensorial pré-registrado.",
    )
    tensor_lab_run.add_argument("source", type=Path)
    tensor_lab_run.add_argument(
        "--preregistration",
        type=Path,
        required=True,
    )
    tensor_lab_run.add_argument("--output", type=Path, required=True)

    tensor_lab_judge = commands.add_parser(
        "tensor-lab-judge",
        help="Recalcula amostras e emite o veredito tensorial imutável.",
    )
    tensor_lab_judge.add_argument(
        "--preregistration",
        type=Path,
        required=True,
    )
    tensor_lab_judge.add_argument("--report", type=Path, required=True)
    tensor_lab_judge.add_argument("--output", type=Path, required=True)

    tensor_lab_verify = commands.add_parser(
        "tensor-lab-verify",
        help="Reproduz selos, métricas e classificação tensorial.",
    )
    tensor_lab_verify.add_argument(
        "--preregistration",
        type=Path,
        required=True,
    )
    tensor_lab_verify.add_argument("--report", type=Path, required=True)
    tensor_lab_verify.add_argument("--verdict", type=Path, required=True)

    tensor_suite_preregister = commands.add_parser(
        "tensor-suite-preregister",
        help="Sela casos ainda não medidos e reinícios em processos novos.",
    )
    tensor_suite_preregister.add_argument("manifest", type=Path)
    tensor_suite_preregister.add_argument(
        "--output", type=Path, required=True
    )
    tensor_suite_preregister.add_argument("--samples", type=int, default=9)
    tensor_suite_preregister.add_argument("--warmups", type=int, default=2)
    tensor_suite_preregister.add_argument(
        "--inner-iterations", type=int, default=25
    )
    tensor_suite_preregister.add_argument(
        "--restarts", type=int, default=3
    )
    tensor_suite_preregister.add_argument(
        "--workers", choices=("1", "2", "4"), default="4"
    )
    tensor_suite_preregister.add_argument(
        "--gemm-workers", choices=("1", "2", "4"), default="1"
    )
    tensor_suite_preregister.add_argument(
        "--provider",
        choices=("owned", "openblas"),
        default="openblas",
    )
    tensor_suite_preregister.add_argument(
        "--bootstrap-resamples", type=int, default=2_000
    )
    tensor_suite_preregister.add_argument(
        "--superiority-threshold", type=float, default=1.0
    )
    tensor_suite_preregister.add_argument(
        "--commercial-threshold", type=float, default=6.0
    )
    tensor_suite_preregister.add_argument(
        "--prior-exploratory-disclosure", required=True
    )
    tensor_suite_preregister.add_argument(
        "--claim-ineligible", action="store_true"
    )

    tensor_suite_run = commands.add_parser(
        "tensor-suite-run",
        help="Executa a agenda selada em processos Python independentes.",
    )
    tensor_suite_run.add_argument("manifest", type=Path)
    tensor_suite_run.add_argument(
        "--preregistration", type=Path, required=True
    )
    tensor_suite_run.add_argument("--output", type=Path, required=True)

    tensor_suite_judge = commands.add_parser(
        "tensor-suite-judge",
        help="Exige unanimidade de casos, reinícios e baselines.",
    )
    tensor_suite_judge.add_argument(
        "--preregistration", type=Path, required=True
    )
    tensor_suite_judge.add_argument("--report", type=Path, required=True)
    tensor_suite_judge.add_argument("--output", type=Path, required=True)

    tensor_suite_verify = commands.add_parser(
        "tensor-suite-verify",
        help="Verifica a cadeia confirmatória multi-processo.",
    )
    tensor_suite_verify.add_argument(
        "--preregistration", type=Path, required=True
    )
    tensor_suite_verify.add_argument("--report", type=Path, required=True)
    tensor_suite_verify.add_argument("--verdict", type=Path, required=True)

    pytorch_doctor = commands.add_parser(
        "pytorch-doctor",
        help="Prova importação, autograd e, opcionalmente, torch.compile.",
    )
    pytorch_doctor.add_argument(
        "--compile",
        action="store_true",
        help="Inclui uma compilação real pelo Inductor CPU.",
    )

    commands.add_parser("doctor", help="Verifica o frontend instalado.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _guard_legacy_research(args.command)
    if args.command == "pytorch-doctor":
        report = probe_pytorch_runtime(check_compile=args.compile)
        print(
            json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if report.available else 3

    if args.command == "doctor":
        print(f"T compiler: {__version__}")
        print(f"Python: {platform.python_version()}")
        print("Frontend Egg: disponível")
        print("Análise Larva: disponível")
        print("Tabela de símbolos: disponível")
        print("CrisálidaIR: disponível")
        print("Backend Python de referência: disponível")
        print("ABI nativa e backend C99: disponível")
        print("Perfil SIMD estrito e relatório vetorial: disponível")
        print("Build reproduzível e chave estrutural tipada: disponível")
        print("Executor de artefatos: disponível")
        print("Grafo def-use da Metamorfose: disponível")
        print("Lote fundido e cache local por operação: disponível")
        print("Buffers tipados e evidência lateral: disponível")
        print("Pesquisa histórica: arquivada e fora do perfil de produto")
        print("Seletor adaptativo Crisálida: disponível")
        print("Treinamento científico: disponível somente em legacy-research")
        print("LarvaTensor e ABI tensorial declarativa: disponível")
        print("Metamorfose Autograd e gradient check: disponível")
        print("Backend CPU tensorial C99/OpenMP: disponível")
        print("PyTorch: não sondado pelo doctor do produto")
        print(f"Opt-in histórico: {LEGACY_RESEARCH_ENV}=1")
        return 0

    try:
        if args.command == "tcap-build":
            artifact = build_learn_tcap(args.source, args.output)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "artifact": str(artifact.tcap_file),
                        "sha256": artifact.artifact_sha256,
                        "content_sha256": artifact.content_sha256,
                        "entry_offset": artifact.entry_offset,
                        "compiler": artifact.compiler,
                        "evidence": str(artifact.evidence_file),
                        "kernel_execution_proven": False,
                        "performance_measured": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "tensor-suite-preregister":
            preregistration = create_tensor_suite_preregistration(
                args.manifest,
                args.output,
                samples=args.samples,
                warmups=args.warmups,
                inner_iterations=args.inner_iterations,
                restarts=args.restarts,
                workers=int(args.workers),
                gemm_workers=int(args.gemm_workers),
                provider=args.provider,
                bootstrap_resamples=args.bootstrap_resamples,
                superiority_threshold=args.superiority_threshold,
                commercial_threshold=args.commercial_threshold,
                prior_exploratory_disclosure=(
                    args.prior_exploratory_disclosure
                ),
                claim_eligible=not args.claim_ineligible,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "experiment_id": preregistration.experiment_id,
                        "preregistration": str(preregistration.path),
                        "cases": len(
                            preregistration.document["design"]["cases"]
                        ),
                        "scheduled_runs": len(
                            preregistration.document["design"]["schedule"]
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "tensor-suite-run":
            report = run_tensor_suite(
                args.manifest,
                args.preregistration,
                args.output,
            )
            print(
                json.dumps(
                    {
                        "ok": report.document["status"] == "COMPLETE",
                        "status": report.document["status"],
                        "report_json": str(report.json_path),
                        "report_html": str(report.html_path),
                        "complete_runs": sum(
                            item["status"] == "COMPLETE"
                            for item in report.document["runs"]
                        ),
                        "scheduled_runs": len(report.document["runs"]),
                        "claims_allowed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if report.document["status"] == "COMPLETE" else 4

        if args.command == "tensor-suite-judge":
            verdict = judge_tensor_suite(
                args.preregistration,
                args.report,
                args.output,
            )
            print(
                json.dumps(
                    {
                        "ok": verdict.classification == "POSITIVE",
                        "classification": verdict.classification,
                        "commercial_gate": verdict.document[
                            "commercial_gate"
                        ],
                        "claim": verdict.document["claim"],
                        "verdict": str(verdict.path),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "tensor-suite-verify":
            checks = verify_tensor_suite_chain(
                args.preregistration,
                args.report,
                args.verdict,
            )
            print("CASULO/T TENSOR SUITE CHAIN IS VALID")
            for check in checks:
                print(f"  [OK] {check}")
            return 0

        if args.command == "tensor-lab-preregister":
            baselines = (
                args.tensor_lab_baselines
                if args.tensor_lab_baselines is not None
                else [
                    TENSOR_LAB_BACKEND_EAGER,
                    TENSOR_LAB_BACKEND_INDUCTOR,
                ]
            )
            preregistration = create_tensor_lab_preregistration(
                args.source,
                args.output,
                wrt=tuple(args.wrt),
                loss=args.loss,
                samples=args.samples,
                warmups=args.warmups,
                inner_iterations=args.inner_iterations,
                workers=int(args.workers),
                gemm_workers=(
                    (
                        args.gemm_workers
                        if args.gemm_workers == "adaptive"
                        else int(args.gemm_workers)
                    )
                    if args.gemm_workers is not None
                    else None
                ),
                provider=args.provider,
                seed=args.seed,
                bootstrap_resamples=args.bootstrap_resamples,
                arena_budget_bytes=args.arena_budget,
                required_baselines=baselines,
                superiority_threshold=args.superiority_threshold,
                commercial_threshold=args.commercial_threshold,
                prior_exploratory_disclosure=(
                    args.prior_exploratory_disclosure
                ),
                prior_same_design_observed=(
                    args.prior_same_design_observed
                ),
                claim_eligible=not args.claim_ineligible,
                target_sample_wall_ms=args.target_sample_ms,
                maximum_inner_iterations=args.maximum_inner_iterations,
                cooldown_ms=args.cooldown_ms,
                cpu_affinity=args.cpu_affinity,
                max_coefficient_of_variation=args.max_cv,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "experiment_id": preregistration.experiment_id,
                        "preregistration": str(preregistration.path),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "tensor-lab-run":
            report = run_tensor_lab(
                args.source,
                args.preregistration,
                args.output,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "claims_allowed": False,
                        "report_json": str(report.json_path),
                        "report_html": str(report.html_path),
                        "quality": {
                            key: value
                            for key, value in report.document[
                                "quality"
                            ].items()
                            if key != "details"
                        },
                        "comparisons": report.document["comparisons"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "tensor-lab-judge":
            verdict = judge_tensor_lab(
                args.preregistration,
                args.report,
                args.output,
            )
            print(
                json.dumps(
                    {
                        "ok": verdict.classification == "POSITIVE",
                        "classification": verdict.classification,
                        "commercial_gate": verdict.document[
                            "commercial_gate"
                        ],
                        "claim": verdict.document["claim"],
                        "verdict": str(verdict.path),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "tensor-lab-verify":
            checks = verify_tensor_lab_chain(
                args.preregistration,
                args.report,
                args.verdict,
            )
            print("CASULO/T TENSOR LAB CHAIN IS VALID")
            for check in checks:
                print(f"  [OK] {check}")
            return 0

        if args.command == "tensor-causal-profile":
            profile = create_causal_profile(
                args.source,
                args.output,
                wrt=tuple(args.wrt),
                loss=args.loss,
                workers=args.workers,
                gemm_workers=(
                    (
                        args.gemm_workers
                        if args.gemm_workers == "adaptive"
                        else int(args.gemm_workers)
                    )
                    if args.gemm_workers is not None
                    else None
                ),
                provider=args.provider,
                arena_budget_bytes=args.arena_budget,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "profile_id": profile.document["profile_id"],
                        "profile_json": str(profile.json_path),
                        "profile_html": str(profile.html_path),
                        "runtime_measured": False,
                        "claim": None,
                        "summary": profile.document["summary"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "tensor-cpu-plan":
            autograd_ir = compile_autograd_file(
                args.source,
                wrt=tuple(args.wrt),
                loss=args.loss,
            )
            plan = plan_tensor_cpu(
                autograd_ir,
                arena_budget_bytes=args.arena_budget,
                workers=args.workers,
                gemm_workers=(
                    (
                        args.gemm_workers
                        if args.gemm_workers == "adaptive"
                        else int(args.gemm_workers)
                    )
                    if args.gemm_workers is not None
                    else None
                ),
                provider=args.provider,
            )
            encoded = json.dumps(
                plan.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            if args.output is not None:
                destination = args.output.expanduser().resolve()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    encoded + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                print(str(destination))
            else:
                print(encoded)
            return 0 if plan.eligible else 4

        if args.command == "tensor-cpu-run":
            report = execute_tensor_cpu_file(
                args.source,
                args.input,
                wrt=tuple(args.wrt),
                loss=args.loss,
                arena_budget_bytes=args.arena_budget,
                workers=args.workers,
                gemm_workers=(
                    (
                        args.gemm_workers
                        if args.gemm_workers == "adaptive"
                        else int(args.gemm_workers)
                    )
                    if args.gemm_workers is not None
                    else None
                ),
                provider=args.provider,
                allow_fallback=not args.no_fallback,
            )
            encoded = json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            if args.output is not None:
                destination = args.output.expanduser().resolve()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    encoded + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                print(str(destination))
            else:
                print(encoded)
            if report.status == "PASS":
                return 0
            if report.status == "FAIL":
                return 1
            if report.status == "FALLBACK":
                return 4
            return 3

        if args.command == "numpy-execute":
            execution = execute_numpy_file(
                args.source,
                args.input,
                wrt=tuple(args.wrt),
                loss=args.loss,
            )
            document = execution.to_dict(
                include_values=not args.summary_only
            )
            encoded = json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
            )
            if args.output is not None:
                destination = args.output.expanduser().resolve()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    encoded + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                print(str(destination))
            else:
                print(encoded)
            return 0

        if args.command == "pytorch-parity":
            report = run_pytorch_parity_file(
                args.source,
                args.input,
                wrt=tuple(args.wrt),
                loss=args.loss,
            )
            encoded = json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            if args.output is not None:
                destination = args.output.expanduser().resolve()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    encoded + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                print(str(destination))
            else:
                print(encoded)
            if report.status is ParityStatus.PASS:
                return 0
            if report.status is ParityStatus.FAIL:
                return 1
            return 3

        if args.command == "autograd-compile":
            autograd_ir = compile_autograd_file(
                args.source,
                wrt=args.wrt,
                loss=args.loss,
            )
            if args.output is not None:
                destination = autograd_ir.write_json(args.output)
                print(str(destination))
            elif args.format == "json":
                print(
                    json.dumps(
                        autograd_ir.to_dict(),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(autograd_ir.render_text(), end="")
            return 0

        if args.command == "autograd-check":
            report = check_gradients_file(
                args.source,
                args.input,
                wrt=args.wrt,
                loss=args.loss,
                epsilon=args.epsilon,
                absolute_tolerance=args.absolute_tolerance,
                relative_tolerance=args.relative_tolerance,
                max_elements=args.max_elements,
            )
            print(
                json.dumps(
                    report.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if report.passed else 1

        if args.command == "tensor-compile":
            tensor_ir = compile_tensor_file(args.source)
            if args.output is not None:
                destination = tensor_ir.write_json(args.output)
                print(str(destination))
            elif args.format == "json":
                print(
                    json.dumps(
                        tensor_ir.to_dict(),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(tensor_ir.render_text(), end="")
            return 0

        if args.command == "init":
            root = init_workspace(args.target, name=args.name)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "workspace": str(root),
                        "manifest": str(root / WORKSPACE_MANIFEST),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "test":
            result = test_workspace(args.target)
            if args.format == "json":
                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(
                    f"{result['workspace']}: "
                    f"{result['modules_checked']} módulos e "
                    f"{result['tests_checked']} testes: ok"
                )
            return 0

        if args.command == "scientific-preregister":
            baselines = (
                args.baselines
                if args.baselines is not None
                else [PYTORCH_EAGER_BASELINE, PYTORCH_COMPILE_BASELINE]
            )
            preregistration = create_training_preregistration(
                args.source,
                args.output,
                records=args.records,
                samples=args.samples,
                warmups=args.warmups,
                workers=args.workers,
                seed=args.seed,
                bootstrap_resamples=args.bootstrap_resamples,
                required_baselines=baselines,
                superiority_threshold=args.superiority_threshold,
                commercial_threshold=args.commercial_threshold,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "experiment_id": preregistration.experiment_id,
                        "preregistration": str(preregistration.path),
                        "seal_sha256": preregistration.seal_sha256,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "scientific-probe":
            probe_result = probe_pytorch_compile(args.output)
            print(
                json.dumps(
                    {
                        "ok": probe_result["status"] == "AVAILABLE",
                        "status": probe_result["status"],
                        "capability": probe_result["capability"],
                        "probe_id": probe_result["probe_id"],
                        "output": str(args.output.expanduser().resolve()),
                        "error": probe_result["error"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "scientific-judge":
            verdict = judge_training_evidence(
                args.preregistration,
                args.report,
                args.output,
            )
            print(
                json.dumps(
                    {
                        "ok": verdict.classification == "POSITIVE",
                        "classification": verdict.classification,
                        "verdict_id": verdict.document["verdict_id"],
                        "output": str(verdict.output_path),
                        "interpretation": verdict.document["interpretation"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "scientific-verify":
            checks = verify_scientific_chain(
                args.preregistration,
                args.report,
                args.probe,
                args.verdict,
            )
            print("CASULO/T SCIENTIFIC CHAIN IS VALID")
            for check in checks:
                print(f"  [OK] {check}")
            print(f"  [OK] {len(checks)} independent gates passed")
            return 0

        if args.command == "training-experiment":
            training_source = resolve_entry_source(
                args.source,
                required_kind="training",
            ) if args.source.is_dir() else args.source
            report = run_training_experiment(
                training_source,
                args.output,
                records=args.records,
                samples=args.samples,
                warmups=args.warmups,
                workers=args.workers,
                seed=args.seed,
                bootstrap_resamples=args.bootstrap_resamples,
                preregistration=args.preregistration,
                baseline=args.baseline,
            )
            output = args.output.expanduser().resolve()
            print(
                json.dumps(
                    {
                        "ok": True,
                        "artifact_id": report.artifact_id,
                        "dataset_sha256": report.dataset["sha256"],
                        "report_json": str(output / "training-report.json"),
                        "report_html": str(output / "training-report.html"),
                        "paired_speedup_median": report.comparison[
                            "paired_speedup_median"
                        ],
                        "paired_speedup_ci95": report.comparison[
                            "paired_speedup_ci95"
                        ],
                        "equivalent_training": report.quality[
                            "equivalent_training"
                        ],
                        "quality_target_reached": report.quality[
                            "quality_target_reached"
                        ],
                        "claim_gate_6x": report.comparison["claim_gate_6x"],
                        "scientific_status": report.scientific["status"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "simd-benchmark":
            target = args.target.expanduser().resolve()
            if target.suffix.lower() == ".t":
                built = ArtifactBuilder().build(target, args.build_dir)
                artifact_dir = built.output_dir
            else:
                artifact_dir = target
            raw_payload = _read_json_input(args.input, args.data)
            if args.repeat < 1:
                raise SimdBenchmarkError("repeat precisa ser positivo")
            payloads = (
                raw_payload * args.repeat
                if isinstance(raw_payload, list)
                else [raw_payload] * args.repeat
            )
            report = benchmark_simd_artifact(
                artifact_dir,
                payloads,
                operation=args.operation,
                samples=args.samples,
                iterations=args.iterations,
            )
            rendered = json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            if args.output is not None:
                output = args.output.expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            return 0

        if args.command == "native-benchmark":
            target = args.target.expanduser().resolve()
            if target.suffix.lower() == ".t":
                built = ArtifactBuilder().build(target, args.build_dir)
                artifact_dir = built.output_dir
            else:
                artifact_dir = target
            raw_payload = _read_json_input(args.input, args.data)
            if args.repeat < 1:
                raise NativeBenchmarkError("repeat precisa ser positivo")
            payloads = (
                raw_payload * args.repeat
                if isinstance(raw_payload, list)
                else [raw_payload] * args.repeat
            )
            report = benchmark_native_artifact(
                artifact_dir,
                payloads,
                operation=args.operation,
                samples=args.samples,
                iterations=args.iterations,
            )
            rendered = json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            if args.output is not None:
                output = args.output.expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            return 0

        if args.command == "experiment":
            target = args.target.expanduser().resolve()
            if target.suffix.lower() == ".t":
                try:
                    built = ArtifactBuilder().build(target, args.build_dir)
                except CompilationFailed as exc:
                    for diagnostic in exc.diagnostics:
                        print(diagnostic.render(), file=sys.stderr)
                    return 1
                artifact_dir = built.output_dir
            else:
                artifact_dir = target
            config = BorboletaConfig(
                records=args.records,
                samples=args.samples,
                iterations=args.iterations,
                warmups=args.warmups,
                seed=args.seed,
                duplicate_rate=args.duplicate_rate,
                bootstrap_resamples=args.bootstrap_resamples,
            )
            dataset = generate_hydrological_dataset(config)
            report = BorboletaLaboratorio().run(
                artifact_dir,
                operation=args.operation,
                config=config,
                dataset=dataset,
            )
            output = args.output.expanduser().resolve()
            output.mkdir(parents=True, exist_ok=True)
            (output / "dataset.json").write_text(
                json.dumps(
                    list(dataset.payloads),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (output / "dataset-manifest.json").write_text(
                json.dumps(
                    dataset.manifest(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            json_path, html_path = report.write(output)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "artifact_id": report.artifact_id,
                        "dataset_sha256": dataset.sha256,
                        "report_json": str(json_path),
                        "report_html": str(html_path),
                        "wall_speedup_median": report.comparison[
                            "wall_speedup_median"
                        ],
                        "electrical_energy_measured": report.energy[
                            "electrical_energy_measured"
                        ],
                        "adaptive_strategy": report.adaptation["decision"][
                            "strategy"
                        ],
                        "adaptive_prediction_correct": report.adaptation[
                            "prediction_correct"
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "benchmark":
            target = args.target.expanduser().resolve()
            if target.suffix.lower() == ".t":
                try:
                    built = ArtifactBuilder().build(
                        target,
                        args.build_dir,
                    )
                except CompilationFailed as exc:
                    for diagnostic in exc.diagnostics:
                        print(diagnostic.render(), file=sys.stderr)
                    return 1
                artifact_dir = built.output_dir
            else:
                artifact_dir = target
            raw_payload = _read_json_input(args.input, args.data)
            if args.repeat < 1:
                raise BenchmarkError("repeat precisa ser positivo")
            payloads = (
                raw_payload * args.repeat
                if isinstance(raw_payload, list)
                else [raw_payload] * args.repeat
            )
            report = benchmark_artifact(
                artifact_dir,
                payloads,
                operation=args.operation,
                samples=args.samples,
                iterations=args.iterations,
            )
            rendered = json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            if args.output is not None:
                output = args.output.expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            return 0

        if args.command == "build":
            source = args.source.expanduser().resolve()
            if source.is_dir():
                built_workspace = build_workspace(source, args.output)
                payload = {
                    "workspace_id": built_workspace.workspace_id,
                    "cache_hit": built_workspace.cache_hit,
                    "entry_artifact": str(
                        built_workspace.entry_artifact
                    ),
                    "entry_kind": built_workspace.entry_kind,
                    "ok": True,
                    "output": str(built_workspace.output_dir),
                }
                if args.native:
                    if built_workspace.entry_kind != "core":
                        raise WorkspaceError(
                            "T4023",
                            "--native ainda exige entrypoint core",
                        )
                    payload["native"] = compile_native_artifact(
                        built_workspace.entry_artifact
                    ).to_dict()
                if args.format == "json":
                    print(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                    )
                else:
                    state = (
                        "cache hit"
                        if built_workspace.cache_hit
                        else "criado"
                    )
                    print(
                        f"workspace build: {state}: "
                        f"{built_workspace.output_dir}"
                    )
                    print(
                        f"workspace: {built_workspace.workspace_id}"
                    )
                    print(
                        f"entry: {built_workspace.entry_artifact}"
                    )
                return 0
            try:
                built = ArtifactBuilder().build(source, args.output)
            except CompilationFailed as exc:
                if args.format == "json":
                    print(
                        json.dumps(
                            {
                                "ok": False,
                                "diagnostics": [
                                    diagnostic.to_dict()
                                    for diagnostic in exc.diagnostics
                                ],
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                else:
                    for diagnostic in exc.diagnostics:
                        print(diagnostic.render(), file=sys.stderr)
                return 1
            payload = {
                "artifact_id": built.artifact_id,
                "cache_hit": built.cache_hit,
                "ok": True,
                "output": str(built.output_dir),
            }
            if args.native:
                payload["native"] = compile_native_artifact(
                    built.output_dir
                ).to_dict()
            if args.format == "json":
                print(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                state = "cache hit" if built.cache_hit else "criado"
                print(f"build: {state}: {built.output_dir}")
                print(f"artifact: {built.artifact_id}")
            return 0

        if args.command == "run":
            target = args.target.expanduser().resolve()
            if target.is_dir() and (target / WORKSPACE_MANIFEST).is_file():
                workspace_build = build_workspace(
                    target,
                    args.build_dir,
                )
                if workspace_build.entry_kind != "core":
                    raise WorkspaceError(
                        "T4024",
                        "t run exige entrypoint core; para treinamento "
                        "use t training-experiment",
                    )
                artifact_dir = workspace_build.entry_artifact
            elif target.suffix.lower() == ".t":
                try:
                    built = ArtifactBuilder().build(
                        target,
                        args.build_dir,
                    )
                except CompilationFailed as exc:
                    for diagnostic in exc.diagnostics:
                        print(diagnostic.render(), file=sys.stderr)
                    return 1
                artifact_dir = built.output_dir
            else:
                artifact_dir = target
            input_payload = _read_json_input(args.input, args.data)
            if args.native_required:
                args.native = True
            if args.native and args.adaptive:
                raise AdaptiveError(
                    "--native e --adaptive são mutuamente exclusivos"
                )
            if args.adaptive:
                if args.no_cache:
                    raise AdaptiveError(
                        "--adaptive e --no-cache são mutuamente exclusivos"
                    )
                if not isinstance(input_payload, list):
                    raise AdaptiveError(
                        "--adaptive exige uma lista JSON de entrada"
                    )
                if args.memory_budget_mb < 1:
                    raise AdaptiveError(
                        "--memory-budget-mb precisa ser positivo"
                    )
                adaptive = run_adaptive_artifact(
                    artifact_dir,
                    input_payload,
                    operation=args.operation,
                    memory_budget_bytes=args.memory_budget_mb * 1024 * 1024,
                )
                executed_payload = adaptive.payload
                is_batch = True
            elif args.native:
                native_executed = run_native_artifact(
                    artifact_dir,
                    input_payload,
                    operation=args.operation,
                    batch=True if args.batch else None,
                    fallback=not args.native_required,
                )
                executed_payload = native_executed.payload
                is_batch = native_executed.batch
                if native_executed.fallback_reason is not None:
                    print(
                        "t: fallback Python: "
                        + native_executed.fallback_reason,
                        file=sys.stderr,
                    )
            else:
                executed = run_artifact(
                    artifact_dir,
                    input_payload,
                    operation=args.operation,
                    batch=True if args.batch else None,
                    use_cache=not args.no_cache,
                )
                executed_payload = executed.payload
                is_batch = executed.batch
            if args.format == "text":
                print(
                    json.dumps(
                        (
                            executed_payload["items"]
                            if is_batch
                            else executed_payload["result"]
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            else:
                print(
                    json.dumps(
                        executed_payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            return 0

        if args.command == "check":
            source = args.source.expanduser().resolve()
            if source.is_dir():
                workspace = check_workspace(source)
                payload = {
                    "ok": True,
                    "workspace": workspace.manifest.name,
                    "entry": workspace.manifest.entry,
                    "modules": [
                        module.to_dict(workspace.root)
                        for module in workspace.modules
                    ],
                    "build_order": list(workspace.build_order),
                    "diagnostics": [],
                }
                if args.format == "json":
                    print(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                    )
                else:
                    print(
                        f"{source}: {len(workspace.modules)} "
                        "módulos: ok"
                    )
                    for module in workspace.build_order:
                        print(f"  {module}")
                return 0
            result = check_file(source)
            if args.format == "json":
                print(
                    json.dumps(
                        {
                            "ok": result.ok,
                            "diagnostics": [
                                diagnostic.to_dict()
                                for diagnostic in result.diagnostics
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            elif result.diagnostics:
                for diagnostic in result.diagnostics:
                    print(diagnostic.render(), file=sys.stderr)
            else:
                print(f"{args.source}: ok")
            return 0 if result.ok else 1

        if args.command == "inspect":
            result = check_file(args.source)
            selected = (
                "symbols"
                if args.symbols
                else "graph"
                if args.graph
                else "ir"
                if args.ir
                else "ast"
            )
            output_format = args.format or (
                "text" if selected in {"ir", "graph"} else "json"
            )
            diagnostics = [
                diagnostic.to_dict()
                for diagnostic in result.diagnostics
            ]
            if selected == "symbols":
                if output_format == "text":
                    print(
                        result.symbols.render_text()
                        if result.symbols is not None
                        else ""
                    )
                else:
                    print(
                        json.dumps(
                            {
                                "symbols": (
                                    result.symbols.to_dict()["symbols"]
                                    if result.symbols is not None
                                    else []
                                ),
                                "diagnostics": diagnostics,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
            elif selected == "graph":
                if result.graph is None:
                    print(
                        json.dumps(
                            {"graph": None, "diagnostics": diagnostics},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                elif output_format == "text":
                    print(result.graph.render_text(), end="")
                else:
                    print(
                        json.dumps(
                            {
                                "graph": result.graph.to_dict(),
                                "diagnostics": diagnostics,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
            elif selected == "ir":
                if result.ir is None:
                    print(
                        json.dumps(
                            {"ir": None, "diagnostics": diagnostics},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                elif output_format == "text":
                    print(result.ir.render_text(), end="")
                else:
                    print(
                        json.dumps(
                            {
                                "ir": result.ir.to_dict(),
                                "diagnostics": diagnostics,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
            else:
                print(
                    json.dumps(
                        {
                            "ast": ast_to_dict(result.program),
                            "diagnostics": diagnostics,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 0 if result.ok else 1
    except (ArtifactError, BackendError) as exc:
        print(f"t: erro de artefato: {exc}", file=sys.stderr)
        return 2
    except BenchmarkError as exc:
        print(f"t: benchmark inválido: {exc}", file=sys.stderr)
        return 2
    except NativeBenchmarkError as exc:
        print(f"t: benchmark nativo inválido: {exc}", file=sys.stderr)
        return 2
    except SimdBenchmarkError as exc:
        print(f"t: benchmark SIMD inválido: {exc}", file=sys.stderr)
        return 2
    except NativeError as exc:
        print(f"t: execução nativa bloqueada: {exc}", file=sys.stderr)
        return 3
    except BorboletaError as exc:
        print(f"t: experimento Borboleta inválido: {exc}", file=sys.stderr)
        return 2
    except AdaptiveError as exc:
        print(f"t: decisão adaptativa inválida: {exc}", file=sys.stderr)
        return 2
    except TrainingError as exc:
        print(f"t: experimento de treinamento inválido: {exc}", file=sys.stderr)
        return 2
    except LearnNativeError as exc:
        print(f"t: lowering nativo learn bloqueado: {exc}", file=sys.stderr)
        return 3
    except WorkspaceError as exc:
        print(f"t: workspace inválido: {exc}", file=sys.stderr)
        return 2
    except ScientificError as exc:
        print(f"t: fidelidade científica violada: {exc}", file=sys.stderr)
        return 2
    except ParityError as exc:
        print(f"t: paridade bloqueada: {exc}", file=sys.stderr)
        return 2
    except AutogradError as exc:
        print(f"t: autograd bloqueado: {exc}", file=sys.stderr)
        return 2
    except TensorError as exc:
        print(f"t: grafo tensorial inválido: {exc}", file=sys.stderr)
        return 2
    except TensorCpuError as exc:
        print(f"t: backend CPU tensorial bloqueado: {exc}", file=sys.stderr)
        return 3
    except TensorLabError as exc:
        print(f"t: laboratório tensorial bloqueado: {exc}", file=sys.stderr)
        return 2
    except TensorSuiteError as exc:
        print(f"t: suíte tensorial bloqueada: {exc}", file=sys.stderr)
        return 2
    except CausalProfilerError as exc:
        print(f"t: profiler causal bloqueado: {exc}", file=sys.stderr)
        return 2
    except ExecutionFailed as exc:
        print(f"t: execução bloqueada: {exc}", file=sys.stderr)
        return 3
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"t: erro de entrada: {exc}", file=sys.stderr)
        return 2
    return 2


def _read_json_input(input_path: str | None, inline: str | None):
    if inline is not None:
        return json.loads(inline)
    if input_path == "-":
        return json.load(sys.stdin)
    if input_path is not None:
        return json.loads(
            Path(input_path)
            .expanduser()
            .resolve()
            .read_text(encoding="utf-8")
        )
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
