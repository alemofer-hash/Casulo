from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .platform_contracts import PlatformError
from .voice_candidate import VoiceCandidate, inspect_voice_cache


Runner = Callable[..., subprocess.CompletedProcess[str]]


def build_voice_bridge(
    candidate: VoiceCandidate,
    cache_root: str | Path,
    repository_root: str | Path,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Build from an already verified cache. This function never downloads."""
    inspection = inspect_voice_cache(candidate, cache_root)
    if not inspection.source_verified:
        raise PlatformError("source ASR pinado não está verificado")
    if not inspection.model_verified:
        raise PlatformError("modelo ASR pinado não está verificado")
    cmake = shutil.which("cmake")
    ninja = shutil.which("ninja")
    if cmake is None or ninja is None:
        raise PlatformError("build ASR exige CMake e Ninja já instalados")
    repository = Path(repository_root).resolve()
    native_source = repository / "native/voice"
    if not (native_source / "CMakeLists.txt").is_file():
        raise PlatformError("fonte first-party do bridge não foi encontrada")

    build_dir = inspection.cache_root / "build" / candidate.engine_commit
    inspection.bridge_path.parent.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    configure = [
        cmake,
        "-S",
        str(native_source),
        "-B",
        str(build_dir),
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DWHISPER_CPP_DIR={inspection.source_dir}",
        f"-DCASULO_VOICE_OUTPUT_DIR={inspection.bridge_path.parent}",
    ]
    compile_command = [
        cmake,
        "--build",
        str(build_dir),
        "--config",
        "Release",
        "--target",
        "casulo_whisper_bridge",
    ]
    _run_checked(runner, configure)
    _run_checked(runner, compile_command)
    if not inspection.bridge_path.is_file():
        raise PlatformError("build terminou sem produzir o bridge esperado")

    report = {
        "schema": "casulo-voice-build/1.0",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "download_performed": False,
        "engine_commit": candidate.engine_commit,
        "model_sha256": candidate.model_sha256,
        "bridge_path": str(inspection.bridge_path),
        "bridge_sha256": _sha256(inspection.bridge_path),
        "configure_argv": configure,
        "build_argv": compile_command,
    }
    receipt = inspection.cache_root / "BUILD.json"
    _write_atomic(receipt, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def _run_checked(runner: Runner, argv: list[str]) -> None:
    try:
        runner(
            argv,
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()[-2000:]
        raise PlatformError(f"build ASR falhou: {detail}") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PlatformError(f"build ASR não concluiu: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
