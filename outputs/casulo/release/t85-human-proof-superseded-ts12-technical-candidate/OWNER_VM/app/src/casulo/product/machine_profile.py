from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import canonical_json, canonical_sha256
from .hosted_shell import ProductFeature
from .local_intelligence import LocalModelRegistry
from .voice_candidate import VoiceCandidate, candidate_doctor_report


MACHINE_PROFILE_SCHEMA = "casulo-machine-profile/1.0"


@dataclass(frozen=True, slots=True)
class ToolObservation:
    name: str
    path: str | None
    required_for: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "present": self.path is not None,
            "required_for": list(self.required_for),
        }


@dataclass(frozen=True, slots=True)
class FeatureAssessment:
    feature: ProductFeature
    status: str
    reasons: tuple[str, ...]
    optional_download_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature.value,
            "status": self.status,
            "reasons": list(self.reasons),
            "optional_download_bytes": self.optional_download_bytes,
        }


@dataclass(frozen=True, slots=True)
class MachineProfile:
    host_id: str
    os_name: str
    os_release: str
    architecture: str
    cpu_name: str
    logical_cpu_count: int
    memory_bytes: int | None
    workspace: str
    workspace_free_bytes: int
    python_version: str
    tools: tuple[ToolObservation, ...]
    features: tuple[FeatureAssessment, ...]
    voice: dict[str, Any] | None
    guide: dict[str, Any] | None
    schema: str = MACHINE_PROFILE_SCHEMA

    def unsigned(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "os": {"name": self.os_name, "release": self.os_release},
            "architecture": self.architecture,
            "cpu": {"name": self.cpu_name, "logical_count": self.logical_cpu_count},
            "memory_bytes": self.memory_bytes,
            "workspace": self.workspace,
            "workspace_free_bytes": self.workspace_free_bytes,
            "python_version": self.python_version,
            "tools": [tool.to_dict() for tool in self.tools],
            "features": [feature.to_dict() for feature in self.features],
            "voice": self.voice,
            "guide": self.guide,
            "network_access_performed": False,
            "mutations_performed": False,
            "account_required": False,
            "third_party_ai_api_required": False,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.unsigned()
        payload["host_id"] = self.host_id
        stable = dict(payload)
        stable.pop("workspace_free_bytes", None)
        if isinstance(stable.get("voice"), dict):
            stable["voice"] = dict(stable["voice"])
            stable["voice"].pop("free_bytes", None)
        payload["profile_sha256"] = canonical_sha256(stable)
        return payload

    def assessment(self, feature: ProductFeature) -> FeatureAssessment:
        return next(item for item in self.features if item.feature is feature)


def collect_machine_profile(
    workspace: str | Path,
    *,
    voice_manifest: str | Path | None = None,
    voice_cache: str | Path | None = None,
    guide_registry: str | Path | None = None,
) -> MachineProfile:
    """Read-only host inspection. It does not create paths or access the network."""
    root = Path(workspace).expanduser().resolve()
    existing = root
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    disk = shutil.disk_usage(existing)
    tools = tuple(
        ToolObservation(name, _find_tool(binary, candidates), required_for)
        for name, binary, candidates, required_for in (
            ("git", "git", (), ("casulo-voice", "casulo-guide", "casulo-native")),
            ("cmake", "cmake", (), ("casulo-voice", "casulo-native")),
            ("ninja", "ninja", (), ("casulo-voice", "casulo-native")),
            ("clang", "clang", (r"C:\Program Files\LLVM\bin\clang.exe",), ("casulo-native",)),
            ("rustc", "rustc", (), ("casulo-native",)),
            ("cargo", "cargo", (), ("casulo-native",)),
            (
                "qemu-system-x86_64",
                "qemu-system-x86_64",
                (r"C:\Program Files\qemu\qemu-system-x86_64.exe",),
                ("casulo-native",),
            ),
            (
                "ovmf-code",
                "__casulo_missing_ovmf_code__",
                (r"C:\Program Files\qemu\share\edk2-x86_64-code.fd",),
                ("casulo-native",),
            ),
            (
                "ovmf-vars",
                "__casulo_missing_ovmf_vars__",
                (r"C:\Program Files\qemu\share\edk2-i386-vars.fd",),
                ("casulo-native",),
            ),
        )
    )
    voice: dict[str, Any] | None = None
    if (voice_manifest is None) != (voice_cache is None):
        raise ValueError("voice_manifest e voice_cache precisam ser informados juntos")
    if voice_manifest is not None and voice_cache is not None:
        voice = candidate_doctor_report(VoiceCandidate.load(voice_manifest), voice_cache)
    guide = LocalModelRegistry(guide_registry).report() if guide_registry is not None else None

    python_ok = sys.version_info >= (3, 11)
    space_ok = disk.free >= 512 * 1024 * 1024
    sounddevice_present = importlib.util.find_spec("sounddevice") is not None
    voice_ready = bool(voice and voice.get("ready") and sounddevice_present)
    minimal_reasons = tuple(
        reason
        for condition, reason in (
            (python_ok, "Python 3.11+ presente"),
            (space_ok, "ao menos 512 MiB livres no workspace"),
        )
        if not condition
    )
    minimal_status = "READY" if not minimal_reasons else "BLOCKED"
    voice_reasons: list[str] = []
    if not sounddevice_present:
        voice_reasons.append("captura hosted sounddevice indisponivel")
    if voice is None:
        voice_reasons.append("manifesto/cache de voz nao informados")
    elif not voice.get("ready"):
        voice_reasons.append("ASR local ainda nao esta integralmente verificado")
    guide_ready = bool(
        guide
        and guide.get("ready") == {"guide": True, "embeddings": True}
        and guide.get("third_party_ai_api_required") is False
    )
    guide_reasons = () if guide_ready else ("modelo local do Guia ainda nao adotado",)
    creator_status = minimal_status
    features = (
        FeatureAssessment(ProductFeature.MINIMAL, minimal_status, minimal_reasons),
        FeatureAssessment(
            ProductFeature.VOICE,
            "READY" if voice_ready and minimal_status == "READY" else "NEEDS_ACTION",
            tuple(voice_reasons),
            0 if voice_ready else int(voice.get("candidate", {}).get("model_size_bytes", 0)) if voice else 0,
        ),
        FeatureAssessment(ProductFeature.GUIDE, "READY" if guide_ready else "NEEDS_ACTION", guide_reasons),
        FeatureAssessment(ProductFeature.CREATOR, creator_status, minimal_reasons),
        FeatureAssessment(
            ProductFeature.FULL,
            "READY" if voice_ready and guide_ready and creator_status == "READY" else "NEEDS_ACTION",
            tuple(voice_reasons) + guide_reasons + minimal_reasons,
        ),
    )
    identity = {
        "node": platform.node(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
    }
    return MachineProfile(
        host_id=hashlib.sha256(canonical_json(identity)).hexdigest()[:24],
        os_name=platform.system(),
        os_release=platform.release(),
        architecture=platform.machine(),
        cpu_name=identity["cpu"],
        logical_cpu_count=os.cpu_count() or 1,
        memory_bytes=_physical_memory_bytes(),
        workspace=str(root),
        workspace_free_bytes=disk.free,
        python_version=platform.python_version(),
        tools=tools,
        features=features,
        voice=voice,
        guide=guide,
    )


def calibrate_local_response(*, duration_ms: int = 100) -> dict[str, Any]:
    """Bounded product micro-calibration; no scientific performance claim."""
    if duration_ms < 10 or duration_ms > 250:
        raise ValueError("duration_ms precisa estar entre 10 e 250")
    started = time.perf_counter_ns()
    deadline = started + duration_ms * 1_000_000
    operations = 0
    digest = b"casulo-machine-profile"
    while time.perf_counter_ns() < deadline:
        digest = hashlib.sha256(digest).digest()
        operations += 1
    ended = time.perf_counter_ns()
    elapsed_ms = (ended - started) / 1_000_000
    return {
        "schema": "casulo-local-calibration/1.0",
        "duration_ms": elapsed_ms,
        "bounded_duration_ms": duration_ms,
        "hash_operations": operations,
        "operations_per_second": operations / max(elapsed_ms / 1000, 1e-9),
        "receipt_sha256": hashlib.sha256(digest).hexdigest(),
        "purpose": "local UX duration estimate only",
        "scientific_benchmark": False,
        "network_access_performed": False,
        "mutations_performed": False,
    }


def _physical_memory_bytes() -> int | None:
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
        return None
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None


def _find_tool(binary: str, candidates: tuple[str, ...]) -> str | None:
    discovered = shutil.which(binary)
    if discovered:
        return discovered
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
    return None
