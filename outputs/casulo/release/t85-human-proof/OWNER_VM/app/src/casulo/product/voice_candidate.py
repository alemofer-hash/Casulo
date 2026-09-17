from __future__ import annotations

import hashlib
import ctypes
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .platform_contracts import PlatformError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class VoiceCandidate:
    manifest_path: Path
    status: str
    engine_name: str
    engine_repository: str
    engine_tag: str
    engine_commit: str
    engine_license: str
    model_name: str
    model_source: str
    model_size_bytes: int
    model_sha256: str
    model_license: str
    requires_user_consent: bool

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VoiceCandidate":
        path = Path(manifest_path).resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PlatformError(f"manifesto de voz inválido: {error}") from error
        if payload.get("schema") != "casulo-dependency-candidate/1.0":
            raise PlatformError("schema de candidato de voz não suportado")
        engine = _mapping(payload, "engine")
        model = _mapping(payload, "model")
        commit = _text(engine, "commit")
        model_hash = _text(model, "sha256")
        if not _GIT_COMMIT.fullmatch(commit):
            raise PlatformError("commit do engine precisa ser SHA-1 completo")
        if not _SHA256.fullmatch(model_hash):
            raise PlatformError("SHA-256 do modelo é inválido")
        size = model.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise PlatformError("tamanho do modelo precisa ser inteiro positivo")
        if payload.get("status") not in {
            "PROPOSED_NOT_DOWNLOADED",
            "CACHED_VERIFIED",
            "ADOPTED",
        }:
            raise PlatformError("estado de candidato de voz desconhecido")
        if payload.get("downloaded") is not False and payload.get("status") == "PROPOSED_NOT_DOWNLOADED":
            raise PlatformError("manifesto proposto não pode afirmar download")
        return cls(
            manifest_path=path,
            status=_text(payload, "status"),
            engine_name=_safe_component(engine, "name"),
            engine_repository=_https_url(engine, "repository"),
            engine_tag=_text(engine, "tag"),
            engine_commit=commit,
            engine_license=_text(engine, "license"),
            model_name=_safe_component(model, "name"),
            model_source=_https_url(model, "source"),
            model_size_bytes=size,
            model_sha256=model_hash,
            model_license=_text(model, "license_declared_by_repository"),
            requires_user_consent=payload.get("requires_user_consent") is True,
        )

    @property
    def consent_phrase(self) -> str:
        return f"DOWNLOAD_{self.engine_name.upper().replace('.', '_')}_{self.model_size_bytes}_BYTES"


@dataclass(frozen=True, slots=True)
class VoiceCacheInspection:
    cache_root: Path
    source_dir: Path
    source_receipt: Path
    model_path: Path
    bridge_path: Path
    source_verified: bool
    model_present: bool
    model_verified: bool
    bridge_present: bool
    free_bytes: int | None
    bridge_loadable: bool = False
    ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo-voice-doctor/1.0",
            "cache_root": str(self.cache_root),
            "source_dir": str(self.source_dir),
            "source_receipt": str(self.source_receipt),
            "model_path": str(self.model_path),
            "bridge_path": str(self.bridge_path),
            "source_verified": self.source_verified,
            "model_present": self.model_present,
            "model_verified": self.model_verified,
            "bridge_present": self.bridge_present,
            "bridge_loadable": self.bridge_loadable,
            "free_bytes": self.free_bytes,
            "ready": self.ready,
        }


def inspect_voice_cache(
    candidate: VoiceCandidate,
    cache_root: str | Path,
) -> VoiceCacheInspection:
    """Read-only inspection. It never creates the cache directory."""
    root = Path(cache_root).expanduser().resolve()
    source_root = root / "sources" / candidate.engine_name / candidate.engine_commit
    source_dir = source_root / "source"
    source_receipt = source_root / "SOURCE.json"
    model_path = root / "models" / f"{candidate.model_sha256}-{candidate.model_name}"
    if sys.platform == "win32":
        library = "casulo_whisper_bridge.dll"
    elif sys.platform == "darwin":
        library = "libcasulo_whisper_bridge.dylib"
    else:
        library = "libcasulo_whisper_bridge.so"
    bridge_path = root / "bin" / library
    source_verified = (
        _source_receipt_matches(source_receipt, candidate)
        and (source_dir / "CMakeLists.txt").is_file()
        and (source_dir / "include/whisper.h").is_file()
        and _git_checkout_matches(source_dir, candidate.engine_commit)
    )
    model_present = model_path.is_file()
    model_verified = (
        model_present
        and model_path.stat().st_size == candidate.model_size_bytes
        and _file_sha256(model_path) == candidate.model_sha256
    )
    existing = root
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    free_bytes = shutil.disk_usage(existing).free if existing.exists() else None
    bridge_present = bridge_path.is_file()
    bridge_loadable = bridge_present and _bridge_abi_loadable(bridge_path)
    return VoiceCacheInspection(
        cache_root=root,
        source_dir=source_dir,
        source_receipt=source_receipt,
        model_path=model_path,
        bridge_path=bridge_path,
        source_verified=source_verified,
        model_present=model_present,
        model_verified=model_verified,
        bridge_present=bridge_present,
        free_bytes=free_bytes,
        bridge_loadable=bridge_loadable,
        ready=source_verified and model_verified and bridge_loadable,
    )


def candidate_doctor_report(
    candidate: VoiceCandidate,
    cache_root: str | Path,
) -> dict[str, Any]:
    inspection = inspect_voice_cache(candidate, cache_root)
    return {
        **inspection.to_dict(),
        "candidate": {
            "status": candidate.status,
            "engine": candidate.engine_name,
            "tag": candidate.engine_tag,
            "commit": candidate.engine_commit,
            "engine_license": candidate.engine_license,
            "model": candidate.model_name,
            "model_size_bytes": candidate.model_size_bytes,
            "model_sha256": candidate.model_sha256,
            "model_license": candidate.model_license,
        },
        "download_performed": False,
        "requires_user_consent": candidate.requires_user_consent,
        "required_consent_phrase": candidate.consent_phrase,
        "asr_pt_br": "READY" if inspection.ready else "NOT_INSTALLED",
    }


def _source_receipt_matches(path: Path, candidate: VoiceCandidate) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        payload.get("schema") == "casulo-voice-source/1.0"
        and payload.get("repository") == candidate.engine_repository
        and payload.get("commit") == candidate.engine_commit
    )


def _git_checkout_matches(source_dir: Path, expected_commit: str) -> bool:
    git = shutil.which("git")
    if git is None or not (source_dir / ".git").exists():
        return False
    try:
        head = subprocess.run(
            [git, "-C", str(source_dir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            [git, "-C", str(source_dir), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return head == expected_commit and not status.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bridge_abi_loadable(path: Path) -> bool:
    try:
        library = ctypes.CDLL(str(path.resolve(strict=True)))
        for symbol in (
            "casulo_whisper_create",
            "casulo_whisper_destroy",
            "casulo_whisper_last_error",
            "casulo_whisper_transcribe_pt_br",
        ):
            getattr(library, symbol)
    except (OSError, AttributeError):
        return False
    return True


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise PlatformError(f"campo {key} precisa ser objeto")
    return value


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlatformError(f"campo {key} precisa ser texto não vazio")
    return value


def _https_url(payload: dict[str, Any], key: str) -> str:
    value = _text(payload, key)
    if not value.startswith("https://"):
        raise PlatformError(f"campo {key} precisa usar HTTPS")
    return value


def _safe_component(payload: dict[str, Any], key: str) -> str:
    value = _text(payload, key)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise PlatformError(f"campo {key} não pode alterar caminhos")
    return value
