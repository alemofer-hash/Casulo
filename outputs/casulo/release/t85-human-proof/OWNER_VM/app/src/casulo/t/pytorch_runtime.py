"""Descoberta e verificação operacional do runtime PyTorch no Casulo/T."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PYTORCH_RUNTIME_PROTOCOL = "casulo-pytorch-runtime/0.1"
_AUTO_MODULE = object()


@dataclass(frozen=True, slots=True)
class PyTorchRuntimeReport:
    protocol: str
    status: str
    python_version: str
    python_executable: str
    numpy_version: str | None
    pytorch_version: str | None
    device: str
    cpu_threads: int | None
    mkl: bool | None
    mkldnn: bool | None
    eager_autograd: str
    inductor: str
    toolchain: dict[str, Any]
    error: dict[str, str] | None

    @property
    def available(self) -> bool:
        return self.status == "AVAILABLE"

    def to_dict(self) -> dict[str, Any]:
        document = asdict(self)
        document["available"] = self.available
        document["timing"] = None
        document["energy_joules"] = None
        return document


def prepare_pytorch_inductor_runtime() -> dict[str, Any]:
    """Ativa um MSVC utilizável e uma saída decodificável pelo Inductor."""

    if os.name != "nt":
        return {
            "status": "NOT_REQUIRED",
            "compiler": shutil.which("c++") or shutil.which("cc"),
            "source": "platform",
            "encoding_policy": None,
            "error": None,
        }

    os.environ["VSLANG"] = "1033"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    compiler = shutil.which("cl.exe")
    source = "PATH"
    error: str | None = None

    if compiler is None:
        try:
            installation = _find_visual_studio()
            vcvars = (
                installation
                / "VC"
                / "Auxiliary"
                / "Build"
                / "vcvars64.bat"
            )
            if not vcvars.is_file():
                raise FileNotFoundError(f"vcvars64.bat ausente: {vcvars}")
            environment = _load_vcvars_environment(vcvars)
            os.environ.update(environment)
            compiler = shutil.which("cl.exe")
            source = str(vcvars)
            if compiler is None:
                raise FileNotFoundError(
                    "vcvars64.bat executou, mas cl.exe não entrou no PATH"
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    return {
        "status": "READY" if compiler is not None else "UNAVAILABLE",
        "compiler": str(Path(compiler).resolve()) if compiler else None,
        "source": source,
        "encoding_policy": {
            "compiler_language": "en-US",
            "subprocess": "utf-8",
        },
        "error": error,
    }


def configure_pytorch_inductor(torch_module: Any) -> bool:
    """Aplica a compatibilidade UTF-8 exigida pelo Inductor no Windows."""

    if os.name != "nt":
        return False
    try:
        cpp_builder = torch_module._inductor.cpp_builder
    except AttributeError:
        try:
            from torch._inductor import cpp_builder
        except (ImportError, AttributeError):
            return False
    cpp_builder.SUBPROCESS_DECODE_ARGS = ("utf-8",)
    return True


def probe_pytorch_runtime(
    *,
    check_compile: bool = False,
    torch_module: Any = _AUTO_MODULE,
    numpy_module: Any = _AUTO_MODULE,
) -> PyTorchRuntimeReport:
    """Prova importação, CPU, autograd e, opcionalmente, Inductor."""

    toolchain = (
        prepare_pytorch_inductor_runtime()
        if check_compile
        else {
            "status": "NOT_CHECKED",
            "compiler": shutil.which("cl.exe"),
            "source": None,
            "encoding_policy": None,
            "error": None,
        }
    )
    numpy_version: str | None = None
    torch_version: str | None = None
    cpu_threads: int | None = None
    mkl: bool | None = None
    mkldnn: bool | None = None
    eager_status = "FAIL"
    inductor_status = "SKIPPED"
    error_payload: dict[str, str] | None = None

    try:
        if numpy_module is _AUTO_MODULE:
            import numpy as numpy_module
        if torch_module is _AUTO_MODULE:
            import torch as torch_module
        if numpy_module is None:
            raise ImportError("NumPy indisponível")
        if torch_module is None:
            raise ImportError("PyTorch indisponível")

        numpy_version = str(numpy_module.__version__)
        torch_version = str(torch_module.__version__)
        cpu_threads = int(torch_module.get_num_threads())
        configuration = str(torch_module.__config__.show())
        mkl = "MKL" in configuration
        mkldnn = bool(
            getattr(
                getattr(torch_module.backends, "mkldnn", None),
                "is_available",
                lambda: False,
            )()
        )

        value = torch_module.tensor(
            [[1.0, 2.0]],
            dtype=torch_module.float64,
            requires_grad=True,
        )
        weight = torch_module.tensor(
            [[3.0], [4.0]],
            dtype=torch_module.float64,
            requires_grad=True,
        )
        loss = (value @ weight).sum()
        loss.backward()
        expected_value_gradient = torch_module.tensor(
            [[3.0, 4.0]],
            dtype=torch_module.float64,
        )
        expected_weight_gradient = torch_module.tensor(
            [[1.0], [2.0]],
            dtype=torch_module.float64,
        )
        if (
            float(loss.item()) != 11.0
            or not torch_module.equal(value.grad, expected_value_gradient)
            or not torch_module.equal(weight.grad, expected_weight_gradient)
        ):
            raise RuntimeError("smoke test eager/autograd divergente")
        eager_status = "PASS"

        if check_compile:
            if toolchain["status"] == "UNAVAILABLE":
                raise RuntimeError(
                    f"toolchain Inductor indisponível: {toolchain['error']}"
                )
            configure_pytorch_inductor(torch_module)

            def operation(tensor: Any) -> Any:
                return torch_module.relu(tensor @ tensor)

            compiled = torch_module.compile(
                operation,
                backend="inductor",
                fullgraph=True,
            )
            sample = torch_module.arange(
                256,
                dtype=torch_module.float64,
            ).reshape(16, 16)
            observed = compiled(sample)
            expected = operation(sample)
            if not torch_module.equal(observed, expected):
                raise RuntimeError("smoke test Inductor divergente")
            compiled(sample)
            inductor_status = "PASS"
    except Exception as exc:
        if check_compile and eager_status == "PASS":
            inductor_status = "FAIL"
        error_payload = {
            "type": type(exc).__name__,
            "message": str(exc)[:4_096],
        }

    available = eager_status == "PASS" and (
        not check_compile or inductor_status == "PASS"
    )
    return PyTorchRuntimeReport(
        protocol=PYTORCH_RUNTIME_PROTOCOL,
        status="AVAILABLE" if available else "UNAVAILABLE",
        python_version=platform.python_version(),
        python_executable=str(Path(sys.executable).resolve()),
        numpy_version=numpy_version,
        pytorch_version=torch_version,
        device="cpu",
        cpu_threads=cpu_threads,
        mkl=mkl,
        mkldnn=mkldnn,
        eager_autograd=eager_status,
        inductor=inductor_status,
        toolchain=toolchain,
        error=error_payload,
    )


def _find_visual_studio() -> Path:
    candidates = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(variable)
        if root:
            candidates.append(
                Path(root)
                / "Microsoft Visual Studio"
                / "Installer"
                / "vswhere.exe"
            )
    vswhere = next((item for item in candidates if item.is_file()), None)
    if vswhere is None:
        raise FileNotFoundError("vswhere.exe não encontrado")
    completed = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        check=True,
        capture_output=True,
    )
    value = completed.stdout.decode("utf-8-sig").strip()
    if not value:
        raise FileNotFoundError("Visual Studio Build Tools C++ não encontrado")
    return Path(value).resolve()


def _load_vcvars_environment(vcvars: Path) -> dict[str, str]:
    command = f'cmd.exe /d /c call "{vcvars}" >nul && set'
    environment = dict(os.environ)
    environment["VSLANG"] = "1033"
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=environment,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()
        raise RuntimeError(
            "vcvars64.bat falhou"
            + (f": {diagnostic}" if diagnostic else "")
        )
    decoded = completed.stdout.decode("utf-8-sig")
    result: dict[str, str] = {}
    for line in decoded.splitlines():
        if "=" not in line or line.startswith("="):
            continue
        name, value = line.split("=", maxsplit=1)
        result[name] = value
    return result
