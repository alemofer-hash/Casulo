from __future__ import annotations

import hashlib
import json
import os
import stat
import shutil
import subprocess
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .platform_contracts import PlatformError
from .voice_candidate import VoiceCandidate, inspect_voice_cache


SourceFetcher = Callable[[VoiceCandidate, Path], str]
ModelFetcher = Callable[[VoiceCandidate, Path], None]


def adopt_voice_candidate(
    candidate: VoiceCandidate,
    cache_root: str | Path,
    *,
    consent: str,
    source_fetcher: SourceFetcher | None = None,
    model_fetcher: ModelFetcher | None = None,
) -> dict[str, Any]:
    """Explicit, transactional network adoption. Never called by doctor/build."""
    if not candidate.requires_user_consent:
        raise PlatformError("candidato sem política de consentimento explícita")
    if consent != candidate.consent_phrase:
        raise PlatformError(
            f"consentimento ausente; use exatamente {candidate.consent_phrase}"
        )
    root = Path(cache_root).expanduser().resolve()
    inspection = inspect_voice_cache(candidate, root)
    adoption_receipt = root / "adoptions" / f"{candidate.model_sha256}.json"
    if inspection.source_verified and inspection.model_verified:
        existing_adoption = _load_existing_adoption(adoption_receipt, candidate)
        if existing_adoption is None:
            existing_adoption = _load_existing_adoption(root / "ADOPTION.json", candidate)
        if existing_adoption is None:
            existing_adoption = {
                "schema": "casulo-voice-adoption/1.0",
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "consent_recorded": True,
                "engine": candidate.engine_name,
                "engine_commit": candidate.engine_commit,
                "engine_license": candidate.engine_license,
                "model": candidate.model_name,
                "model_size_bytes": candidate.model_size_bytes,
                "model_sha256": candidate.model_sha256,
                "model_license": candidate.model_license,
                "source_path": str(inspection.source_dir),
                "model_path": str(inspection.model_path),
                "model_downloaded_this_run": False,
                "build_performed": False,
                "enabled": False,
                "reconciled_verified_cache": True,
            }
            adoption_receipt.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(adoption_receipt, existing_adoption)
            _write_atomic(root / "ADOPTION.json", existing_adoption)
        return {
            **existing_adoption,
            "model_downloaded_this_run": False,
            "build_performed": False,
            "enabled": False,
            "reused_verified_cache": True,
        }
    existing = root
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    required_free = candidate.model_size_bytes * 3 + 500 * 1024 * 1024
    if not existing.exists() or shutil.disk_usage(existing).free < required_free:
        raise PlatformError(f"espaço insuficiente; necessários {required_free} bytes livres")

    source_root = root / "sources" / candidate.engine_name / candidate.engine_commit
    source_dir = source_root / "source"
    source_receipt = source_root / "SOURCE.json"
    model_dir = root / "models"
    model_path = model_dir / f"{candidate.model_sha256}-{candidate.model_name}"
    source_fetch = source_fetcher or _clone_exact_source
    model_fetch = model_fetcher or _download_exact_model
    reuse_verified_source = inspection.source_verified

    source_root.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    adoption_receipt.parent.mkdir(parents=True, exist_ok=True)
    if not reuse_verified_source and (source_dir.exists() or source_receipt.exists()):
        raise PlatformError("cache de source já existe; execute doctor antes de qualquer reparo")
    if model_path.exists():
        if _file_signature(model_path) != (
            candidate.model_size_bytes,
            candidate.model_sha256,
        ):
            raise PlatformError("modelo existente diverge do candidato pinado")
        model_downloaded = False
    else:
        model_downloaded = True

    source_stage = source_root / f".staging-source-{uuid.uuid4().hex}"
    model_stage = model_dir / f".staging-model-{uuid.uuid4().hex}"
    source_committed = False
    source_receipt_created = False
    model_committed = False
    adoption_written = False
    try:
        if not reuse_verified_source:
            observed_commit = source_fetch(candidate, source_stage)
            if observed_commit != candidate.engine_commit:
                raise PlatformError("checkout não corresponde ao commit pinado")
            if not (source_stage / "CMakeLists.txt").is_file() or not (
                source_stage / "include/whisper.h"
            ).is_file():
                raise PlatformError("checkout ASR não contém a interface esperada")
            os.replace(source_stage, source_dir)
            source_committed = True
            _write_atomic(
                source_receipt,
                {
                    "schema": "casulo-voice-source/1.0",
                    "repository": candidate.engine_repository,
                    "tag": candidate.engine_tag,
                    "commit": candidate.engine_commit,
                    "license": candidate.engine_license,
                },
            )
            source_receipt_created = True
        if model_downloaded:
            model_fetch(candidate, model_stage)
            if _file_signature(model_stage) != (
                candidate.model_size_bytes,
                candidate.model_sha256,
            ):
                raise PlatformError("modelo baixado falhou tamanho/SHA-256")
            os.replace(model_stage, model_path)
            model_committed = True
        report = {
            "schema": "casulo-voice-adoption/1.0",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "consent_recorded": True,
            "engine": candidate.engine_name,
            "engine_commit": candidate.engine_commit,
            "engine_license": candidate.engine_license,
            "model": candidate.model_name,
            "model_size_bytes": candidate.model_size_bytes,
            "model_sha256": candidate.model_sha256,
            "model_license": candidate.model_license,
            "source_path": str(source_dir),
            "model_path": str(model_path),
            "model_downloaded_this_run": model_downloaded,
            "build_performed": False,
            "enabled": False,
        }
        _write_atomic(adoption_receipt, report)
        _write_atomic(root / "ADOPTION.json", report)
        adoption_written = True
        return report
    except BaseException:
        _remove_staging(source_stage, source_root)
        _remove_staging(model_stage, model_dir)
        if source_committed:
            _remove_committed_source(source_dir, source_root)
        if source_receipt_created and source_receipt.exists():
            source_receipt.unlink()
        if model_committed and model_path.exists():
            model_path.unlink()
        if adoption_written:
            if adoption_receipt.exists():
                adoption_receipt.unlink()
            adoption = root / "ADOPTION.json"
            if adoption.exists() and _load_existing_adoption(adoption, candidate) is not None:
                adoption.unlink()
        raise


def _clone_exact_source(candidate: VoiceCandidate, target: Path) -> str:
    git = shutil.which("git")
    if git is None:
        raise PlatformError("Git é necessário para obter o source pinado")
    try:
        subprocess.run(
            [
                git,
                "-c",
                "core.longpaths=true",
                "-c",
                "core.autocrlf=false",
                "clone",
                "--branch",
                candidate.engine_tag,
                "--depth",
                "1",
                "--no-recurse-submodules",
                candidate.engine_repository,
                str(target),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        head = subprocess.run(
            [git, "-c", "core.longpaths=true", "-C", str(target), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            [
                git,
                "-c",
                "core.longpaths=true",
                "-C",
                str(target),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()[-2000:]
        raise PlatformError(f"checkout ASR falhou: {detail}") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PlatformError(f"checkout ASR não concluiu: {error}") from error
    if status.strip():
        raise PlatformError("checkout ASR nasceu modificado")
    return head


def _download_exact_model(candidate: VoiceCandidate, target: Path) -> None:
    request = urllib.request.Request(
        candidate.model_source,
        headers={"User-Agent": "Casulo-Voice-Adopter/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, target.open("xb") as output:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) != candidate.model_size_bytes:
                raise PlatformError("Content-Length do modelo diverge do manifesto")
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > candidate.model_size_bytes:
                    raise PlatformError("download do modelo excedeu tamanho pinado")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, ValueError) as error:
        raise PlatformError(f"download do modelo falhou: {error}") from error


def _file_signature(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def _load_existing_adoption(
    path: Path,
    candidate: VoiceCandidate,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "casulo-voice-adoption/1.0"
        or payload.get("engine_commit") != candidate.engine_commit
        or payload.get("model_sha256") != candidate.model_sha256
        or payload.get("consent_recorded") is not True
    ):
        return None
    return payload


def _remove_staging(path: Path, expected_parent: Path) -> None:
    if not path.exists():
        return
    resolved = path.resolve()
    if resolved.parent != expected_parent.resolve() or not resolved.name.startswith(".staging-"):
        raise PlatformError("limpeza recusou alvo fora do staging de voz")
    if resolved.is_dir() and not resolved.is_symlink():
        shutil.rmtree(resolved, onerror=_remove_readonly)
    else:
        resolved.chmod(stat.S_IWRITE)
        resolved.unlink()


def _remove_committed_source(path: Path, expected_parent: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != expected_parent.resolve() or resolved.name != "source":
        raise PlatformError("rollback recusou source fora do cache de voz")
    shutil.rmtree(resolved, onerror=_remove_readonly)


def _remove_readonly(function: Callable[..., Any], path: str, _error: Any) -> None:
    """Clear Windows checkout attributes only inside a previously validated tree."""
    os.chmod(path, stat.S_IWRITE)
    function(path)
