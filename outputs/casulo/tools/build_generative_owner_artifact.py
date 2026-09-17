from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OWNER_SOURCE = ROOT / "private/casulo-owner/src/casulo_owner"
SOURCE_ALLOWLIST = (
    "dialogue_core.py",
    "generative_agent_probe.py",
    "generative_engine.py",
    "generative_forge.py",
    "generative_model.py",
    "local_model_runtime.py",
    "verifier_repair.py",
    "inspection.py",
    "einstein_solver_kernel.py",
    "scientific_solver.py",
)
FORBIDDEN = (
    b"DeterministicFakeEngine",
    b"LocalGuidePolicy",
    b"LocalOwnerMotor",
    b"OwnerEngineAdapter",
    b"CloudEngineClient",
    b"api.openai.com",
    b"api.anthropic.com",
)
GENERATIVE_INIT = b'''"""Casulo owner generative artifact: private and non-redistributable."""\n\nfrom .dialogue_core import (\n    GenerativeDialogueCore, RelationshipProfile, RelationalMode,\n    SCIENCE_BROS_CONTRACT,\n)\nfrom .generative_engine import (\n    AppendOnlyTraceStore, ContextAssembler, ContextItem, ContextTrust,\n    OwnerContextStore, OwnerGenerativeEngineAdapter, OwnerTurnContext,\n    make_owner_request,\n)\nfrom .generative_forge import (\n    IntentPlanner, TProgramSynthesizer, compile_generated_project,\n)\nfrom .generative_model import GenerativeCandidate, GenerativeModelError\nfrom .local_model_runtime import (\n    ChatMessage, GenerationRequest, LocalModelRuntime, SamplingPolicy,\n    StochasticTrace,\n)\n\n__all__ = [\n    "AppendOnlyTraceStore", "ChatMessage", "ContextAssembler", "ContextItem",\n    "ContextTrust", "GenerationRequest", "GenerativeCandidate",\n    "GenerativeDialogueCore", "GenerativeModelError", "IntentPlanner",\n    "LocalModelRuntime", "OwnerContextStore", "OwnerGenerativeEngineAdapter",\n    "OwnerTurnContext", "RelationshipProfile", "RelationalMode",\n    "SamplingPolicy", "SCIENCE_BROS_CONTRACT", "StochasticTrace",\n    "TProgramSynthesizer", "compile_generated_project", "make_owner_request",\n]\n'''


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_write(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, payload)


def build(output: Path, candidate_path: Path, *, semantic_multiverse: bool = False) -> dict[str, object]:
    output = output.resolve()
    candidate_path = candidate_path.resolve(strict=True)
    if output.exists() or output.is_symlink():
        raise RuntimeError("artifact destination already exists; overwrite denied")
    payloads: dict[str, bytes] = {"casulo_owner/__init__.py": GENERATIVE_INIT}
    selected_sources = (*SOURCE_ALLOWLIST, *(("semantic_multiverse.py",) if semantic_multiverse else ()))
    for filename in selected_sources:
        source = OWNER_SOURCE / filename
        payloads[f"casulo_owner/{filename}"] = source.read_bytes()
    payloads["casulo_owner/assets/generative-candidate.json"] = candidate_path.read_bytes()

    findings: list[dict[str, str]] = []
    for name, payload in payloads.items():
        for forbidden in FORBIDDEN:
            if forbidden.lower() in payload.lower():
                findings.append({"file": name, "forbidden": forbidden.decode("ascii")})
    if findings:
        raise RuntimeError(f"forbidden reference engine component: {findings}")

    candidate = json.loads(payloads["casulo_owner/assets/generative-candidate.json"])
    manifest = {
        "schema": "casulo-owner-generative-artifact/1.0",
        "profile": "casulo-owner",
        "redistributable": False,
        "owner": "Guilherme Moura Fernandes",
        "engine_adapter": "OwnerGenerativeEngineAdapter",
        "engine_boundary": "owner-direct-local-neural-first-party",
        "reference_engine_included": False,
        "fake_engine_included": False,
        "commercial_ai_sdk_included": False,
        "external_ai_endpoint_included": False,
        "model_weights_embedded": False,
        "model_loaded_from_verified_local_cache": True,
        "candidate_id": candidate["candidate_id"],
        "model_sha256": candidate["model"]["sha256"],
        "runtime_archive_sha256": candidate["runtime"]["sha256"],
        "cloud_state": "RELEASE_LOCKED",
        "public_state": "FROZEN",
        "usb_state": "PROHIBITED",
        "semantic_multiverse": semantic_multiverse,
        "files": [
            {"path": name, "bytes": len(value), "sha256": sha256_bytes(value)}
            for name, value in sorted(payloads.items())
        ],
    }
    payloads["OWNER_ARTIFACT.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x") as archive:
        for name, payload in sorted(payloads.items()):
            _zip_write(archive, name, payload)
    audit_report = audit(output)
    if not audit_report["pass"]:
        raise RuntimeError(f"generative owner artifact audit failed: {audit_report}")
    return {
        "schema": "casulo-owner-generative-build-result/1.0",
        "artifact": str(output),
        "artifact_sha256": sha256_file(output),
        "artifact_bytes": output.stat().st_size,
        "audit": audit_report,
    }


def audit(path: Path) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    names: list[str] = []
    adapter_present = False
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            names.append(name)
            payload = archive.read(name)
            adapter_present |= b"class OwnerGenerativeEngineAdapter" in payload
            for forbidden in FORBIDDEN:
                if forbidden.lower() in payload.lower():
                    findings.append({"file": name, "forbidden": forbidden.decode("ascii")})
    expected = {
        "OWNER_ARTIFACT.json",
        "casulo_owner/__init__.py",
        "casulo_owner/dialogue_core.py",
        "casulo_owner/generative_agent_probe.py",
        "casulo_owner/generative_engine.py",
        "casulo_owner/generative_forge.py",
        "casulo_owner/generative_model.py",
        "casulo_owner/local_model_runtime.py",
        "casulo_owner/verifier_repair.py",
        "casulo_owner/inspection.py",
        "casulo_owner/einstein_solver_kernel.py",
        "casulo_owner/scientific_solver.py",
        "casulo_owner/assets/generative-candidate.json",
    }
    if "casulo_owner/semantic_multiverse.py" in names:
        expected.add("casulo_owner/semantic_multiverse.py")
    return {
        "schema": "casulo-owner-generative-artifact-audit/1.0",
        "files": names,
        "allowlist_exact": set(names) == expected,
        "generative_adapter_present": adapter_present,
        "forbidden_findings": findings,
        "reference_engine_absent": not findings,
        "pass": set(names) == expected and adapter_present and not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build allowlisted owner generative artifact")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--semantic-multiverse", action="store_true")
    args = parser.parse_args()
    if args.report.exists() or args.report.is_symlink():
        raise SystemExit("report already exists; overwrite denied")
    result = build(args.output, args.candidate, semantic_multiverse=args.semantic_multiverse)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
