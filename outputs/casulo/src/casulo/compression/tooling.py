from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


TOOL_SPECS = {
    "ffmpeg": {
        "version_args": ("-version",),
        "license": "GPL-3.0-or-later for the installed Gyan full build",
        "role": "video decode/encode and lossless pixel-domain controls",
    },
    "ffprobe": {
        "version_args": ("-version",),
        "license": "same FFmpeg build",
        "role": "authoritative stream metadata probe",
    },
    "zstd": {
        "version_args": ("--version",),
        "license": "BSD-3-Clause",
        "role": "general-purpose compression baseline",
    },
    "7z": {
        "version_args": (),
        "license": "LGPL-2.1-or-later with unRAR restriction",
        "role": "archive baseline",
    },
    "duckdb": {
        "version_args": ("--version",),
        "license": "MIT",
        "role": "100-million-row dataset validation and row-count oracle",
    },
    "aria2c": {
        "version_args": ("--version",),
        "license": "GPL-2.0-or-later",
        "role": "resumable transfer of large public evidence sources",
    },
}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _candidate_paths(name: str) -> list[Path]:
    candidates: list[Path] = []
    resolved = shutil.which(name)
    if resolved:
        candidates.append(Path(resolved))

    local_value = os.environ.get("LOCALAPPDATA")
    if local_value:
        packages = Path(local_value) / "Microsoft" / "WinGet" / "Packages"
        patterns = {
            "ffmpeg": "Gyan.FFmpeg_*/*/bin/ffmpeg.exe",
            "ffprobe": "Gyan.FFmpeg_*/*/bin/ffprobe.exe",
            "zstd": "Meta.Zstandard_*/*/zstd.exe",
            "duckdb": "DuckDB.cli_*/duckdb.exe",
            "aria2c": "aria2.aria2_*/*/aria2c.exe",
        }
        if pattern := patterns.get(name):
            candidates.extend(sorted(packages.glob(pattern)))

    if name == "7z":
        candidates.extend(
            [
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "7-Zip"
                / "7z.exe",
                Path.home() / "OneDrive" / "Desktop" / "7-Zip" / "7z.exe",
            ]
        )
    return candidates


def resolve_tool(name: str) -> Path | None:
    if name not in TOOL_SPECS:
        raise ValueError(f"ferramenta não registrada: {name}")
    for candidate in _candidate_paths(name):
        try:
            if candidate.is_file():
                return candidate.resolve(strict=True)
        except OSError:
            continue
    return None


def doctor_report() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for name, spec in TOOL_SPECS.items():
        path = resolve_tool(name)
        if path is None:
            tools[name] = {**spec, "status": "MISSING"}
            continue
        try:
            completed = subprocess.run(
                [str(path), *spec["version_args"]],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                shell=False,
            )
            version_output = [
                line.strip()
                for line in (completed.stdout or completed.stderr).splitlines()
                if line.strip()
            ]
            version = version_output[0] if version_output else "unknown"
            status = "READY" if completed.returncode in {0, 1, 2} else "BROKEN"
        except (OSError, subprocess.TimeoutExpired) as exc:
            version = type(exc).__name__
            status = "BROKEN"
        tools[name] = {
            **spec,
            "status": status,
            "path": str(path),
            "sha256": _hash_file(path),
            "version": version,
        }
    return {
        "schema": "casulo.lossless-doctor/0.1",
        "ready": all(tool["status"] == "READY" for tool in tools.values()),
        "tools": tools,
    }
