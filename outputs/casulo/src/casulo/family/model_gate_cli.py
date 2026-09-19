from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .model_gate import LoopbackLlamaServer, ModelGateError, ModelProfile, run_functional_probes, run_soak


PROFILE_CHOICES = (
    "q4-vulkan",
    "q5-vulkan",
    "q4-cpu",
    "qwen25-q4-vulkan",
    "qwen25-q3-vulkan",
    "qwen25-q2-vulkan",
    "qwen25-q2-cpu",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_profile(profile_id: str, cache: Path, manifest: Path) -> tuple[ModelProfile, dict[str, Any]]:
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("schema") != "casulo.family.day2-model-candidates/1.0":
        raise ModelGateError("manifesto Day 2 inválido")
    is_qwen25 = profile_id.startswith("qwen25-")
    model_key = "q5_k_m" if profile_id == "q5-vulkan" else (
        "q3_k_m" if profile_id == "qwen25-q3-vulkan" else (
            "q2_k" if profile_id in {"qwen25-q2-vulkan", "qwen25-q2-cpu"} else "q4_k_m"
        )
    )
    runtime_key = "cpu" if profile_id in {"q4-cpu", "qwen25-q2-cpu"} else "vulkan"
    model_family = document["resource_fit_model"] if is_qwen25 else document["model"]
    candidate = model_family["candidates"][model_key]
    files = candidate.get("files", [candidate])
    model_dir = cache / "models" / ("qwen2.5-7b-instruct" if is_qwen25 else "")
    model_file = candidate.get("entry_file", candidate.get("file"))
    if not isinstance(model_file, str):
        raise ModelGateError("arquivo de entrada ausente no manifesto")
    model = model_dir / model_file
    executable = cache / "runtimes" / runtime_key / "llama-server.exe"
    verified_files: list[dict[str, Any]] = []
    for item in files:
        path = model_dir / item["file"]
        if path.stat().st_size != item["bytes"] or _sha256(path) != item["sha256"]:
            raise ModelGateError("modelo diverge do manifesto congelado")
        verified_files.append(
            {"file": item["file"], "bytes": item["bytes"], "sha256": item["sha256"]}
        )
    profile = ModelProfile(
        profile_id=("qwen2.5-7b" if is_qwen25 else "qwen3-8b") + f"-{model_key}-{runtime_key}",
        executable=executable,
        model=model,
        device="none" if runtime_key == "cpu" else "Vulkan0",
        gpu_layers=0 if runtime_key == "cpu" else 99,
        cache_type_k="f16" if is_qwen25 else "q4_0",
        cache_type_v="f16" if is_qwen25 else "q4_0",
        no_host=runtime_key != "cpu",
    )
    identity = {
        "repository": model_family["repository"],
        "revision": model_family["revision"],
        "license": model_family["license"],
        "model_key": model_key,
        "model_file": model_file,
        "model_files": verified_files,
        "runtime_profile": runtime_key,
        "runtime_commit": document["runtime"]["commit"],
        "context_tokens": document["context_tokens"],
        "cache_type_k": profile.cache_type_k,
        "cache_type_v": profile.cache_type_v,
        "batch_size": profile.batch_size,
        "ubatch_size": profile.ubatch_size,
        "flash_attention": profile.flash_attention,
        "no_host": profile.no_host,
    }
    return profile, identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Casulo Family Day 2 local-model gate")
    parser.add_argument("--profile", choices=PROFILE_CHOICES, required=True)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", "")) / "Casulo/family-rp01/day2",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--soak-seconds", type=int, default=0)
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args(argv)

    profile, identity = _load_profile(args.profile, args.cache_root.resolve(), args.manifest.resolve())
    report: dict[str, Any] = {
        "schema": "casulo.family.day2-model-gate/1.0",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "profile": identity,
        "network_scope": "127.0.0.1-only",
        "external_network_required": False,
    }

    def persist() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    server = LoopbackLlamaServer(profile)
    startup_started = time.monotonic()
    server.start()
    report["startup_seconds"] = round(time.monotonic() - startup_started, 3)
    report["listener"] = f"127.0.0.1:{server.port}"
    try:
        report["functional"] = run_functional_probes(server)
        if args.soak_seconds:
            def checkpoint(soak: dict[str, Any]) -> None:
                report["soak"] = soak
                report["status"] = "RUNNING"
                report["pass"] = False
                persist()

            report["soak"] = run_soak(
                server,
                duration_seconds=args.soak_seconds,
                interval_seconds=args.interval_seconds,
                checkpoint=checkpoint,
            )
    finally:
        server.close()
    report["ended_utc"] = datetime.now(UTC).isoformat()
    report["pass"] = report["functional"]["pass"] and (
        "soak" not in report or report["soak"]["pass"]
    )
    report["status"] = "PASS" if report["pass"] else "FAIL"
    persist()
    print(json.dumps({"status": "PASS" if report["pass"] else "FAIL", "output": str(args.output)}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ModelGateError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
