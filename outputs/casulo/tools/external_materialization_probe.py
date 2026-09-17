from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from casulo.product.capabilities import Effect
from casulo.product.creation_pipeline import creation_units
from casulo.product.domain import CreationSpec, CreationState
from casulo.product.materializer import ExecutableAgentBundle, MaterializedPackageImporter, Materializer
from casulo.product.simulation import SimulatedResponse, SimulationCapabilityDouble, SimulationPlan, SimulationRuntime, SimulationStep
from casulo.product.t_forge import TForge
from casulo.t import __version__ as T_VERSION
from casulo.t.artifact import ArtifactBuilder
from casulo.t.resource import ResourceContract, SemanticClass
from casulo.t.tcap import TcapSegment, build_tcap, parse_tcap


SIGNATURE_LABEL = "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def simulation_for(creation: CreationSpec):
    confirmation = CreationSpec(creation.creation_id, creation.version, CreationState.CONFIRMATION, creation.content, creation.capabilities)
    plan = SimulationPlan(
        f"simulation:{creation.version}", creation.creation_id,
        (SimulationStep("local-preview", Effect.NETWORK_CONNECT, "preview", {"url": "simulation://local"}, (), (("behavior", "tone"),), (f"human:agreement:{creation.version}",)),),
        (f"human:agreement:{creation.version}",),
    )
    return SimulationRuntime({Effect.NETWORK_CONNECT: SimulationCapabilityDouble(Effect.NETWORK_CONNECT, (SimulatedResponse(True, {"virtual": True}),))}).run(confirmation, plan)


def sign_and_verify(archive: Path, key: Path, evidence: Path, identity: str) -> dict[str, str | bool]:
    public = Path(str(key) + ".pub").resolve(strict=True)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "casulo-release", str(archive)], check=True, capture_output=True, shell=False)
    signature = Path(str(archive) + ".sig")
    copied_signature = evidence / f"{archive.name}.sig"
    shutil.copyfile(signature, copied_signature)
    allowed = evidence / "ALLOWED_SIGNERS"
    allowed.write_text(f"{identity} {public.read_text(encoding='ascii').strip()}\n", encoding="ascii", newline="\n")
    copied_public = evidence / "SIGNING_KEY.pub"
    copied_public.write_bytes(public.read_bytes())
    verified = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", identity, "-n", "casulo-release", "-s", str(copied_signature)],
        input=archive.read_bytes(), capture_output=True, check=False, shell=False,
    )
    return {"label": SIGNATURE_LABEL, "archive_sha256": sha(archive), "signature_sha256": sha(copied_signature), "verified": verified.returncode == 0}


def clean_environment() -> dict[str, str]:
    keep = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT") if name in os.environ}
    keep.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    return keep


def run_clean(directory: Path, operation: str) -> dict[str, object]:
    env = clean_environment()
    cli = subprocess.run(
        [sys.executable, "-X", "utf8", "-I", str(directory / "agent.py"), operation, "-"],
        input=json.dumps({"value": "pedido externo inédito"}), text=True, encoding="utf-8",
        capture_output=True, cwd=directory, env=env, check=False, timeout=15,
    )
    server = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-I", str(directory / "api.py"), "--port", "0"],
        cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    try:
        if server.stdout is None:
            raise RuntimeError("service stdout unavailable")
        endpoint = json.loads(server.stdout.readline())
        base = f"http://127.0.0.1:{endpoint['port']}"
        with urllib.request.urlopen(base + "/health", timeout=5) as response:
            health = json.loads(response.read())
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
            csp = response.headers.get("Content-Security-Policy")
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=5)
    return {
        "clean_environment": True,
        "python_isolated_flag": True,
        "pythonpath_present": "PYTHONPATH" in env,
        "repo_in_cwd": (directory / ".git").exists(),
        "cli": {"returncode": cli.returncode, "stdout": cli.stdout, "stderr": cli.stderr},
        "api_health": health,
        "desktop": {"served": "Criação Casulo" in html, "csp": csp},
        "service_stopped": server.poll() is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo external materialization clean-room probe")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clean-root", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    args = parser.parse_args()
    repo, output, clean_root, key = args.repo.resolve(), args.output.resolve(), args.clean_root.resolve(), args.signing_key.resolve(strict=True)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output is not empty")
    if clean_root.exists() and any(clean_root.iterdir()):
        raise SystemExit("clean root is not empty")
    output.mkdir(parents=True, exist_ok=True)
    clean_root.mkdir(parents=True, exist_ok=True)
    source = output / "external-agent.t"
    source.write_text(
        'language T/1.1\nmodule casulo.external.proof\n\ncapability manifest\n\nfield Input\n  trace value: Text\n\ncondense MaterializedAnswer in Input\n  effects [manifest]\n  emit "resposta externa Casulo"\n',
        encoding="utf-8", newline="\n",
    )
    built = ArtifactBuilder().build(source, output / "compiled")
    operation = built.manifest["operations"][0]["name"]
    executable = (built.output_dir / "casulo_artifact.py").read_bytes()
    tcap = build_tcap(
        segments=(
            TcapSegment("code", executable, "rx", alignment=16),
            TcapSegment("source", source.read_bytes(), "r"),
            TcapSegment("ir", (built.output_dir / "crisalida.ir.json").read_bytes(), "r"),
            TcapSegment("graph", (built.output_dir / "metamorfose.graph.json").read_bytes(), "r"),
        ),
        target="python-hosted", abi="casulo-python/1", entry_segment="code", entry_offset=0,
        compiler={"name": "T", "version": T_VERSION, "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()},
        resource_contract=ResourceContract(64 * 1024 * 1024, 8 * 1024 * 1024, 1, SemanticClass.FLOW, True, "integer", ("console", "memory"), {"result": "manifest emission"}, {"invalid": "quarantine"}),
        capability_requirements=("manifest",),
    )
    parse_tcap(tcap)
    bundle = ExecutableAgentBundle(built.artifact_id, operation, executable, built.manifest, tcap, {"schema": "casulo.generated-project/1.0", "entry_unit": "external-agent"}, source.read_bytes())
    creation_v1 = CreationSpec("creation:external-proof", 1, CreationState.AGREEMENT, {"identity": {"purpose": "prova externa"}, "behavior": {"tone": "direto"}}, frozenset({"network.connect"}))
    forge_v1 = TForge().compile(creation_units(creation_v1))
    export_root = output / "exports"
    receipt_v1 = Materializer(export_root).materialize(creation_v1, forge_receipt=forge_v1, simulation_receipt=simulation_for(creation_v1), executable_bundle=bundle, signature_class=SIGNATURE_LABEL)
    imported_v1 = MaterializedPackageImporter().import_archive(receipt_v1.archive)
    creation_v2 = CreationSpec(imported_v1.creation.creation_id, 2, CreationState.AGREEMENT, {"identity": {"purpose": "prova externa"}, "behavior": {"tone": "mais conciso"}}, imported_v1.creation.capabilities, imported_v1.creation.rejected_delta_ids)
    forge_v2 = TForge().compile(creation_units(creation_v2))
    receipt_v2 = Materializer(export_root).materialize(creation_v2, forge_receipt=forge_v2, simulation_receipt=simulation_for(creation_v2), executable_bundle=bundle, signature_class=SIGNATURE_LABEL)
    imported_v2 = MaterializedPackageImporter().import_archive(receipt_v2.archive)
    with zipfile.ZipFile(receipt_v2.archive) as archive:
        archive.extractall(clean_root)
    clean = run_clean(clean_root, operation)
    signatures = [sign_and_verify(receipt_v1.archive, key, output, "casulo-rc9-dev-v1"), sign_and_verify(receipt_v2.archive, key, output, "casulo-rc9-dev-v2")]
    manifest = json.loads((receipt_v2.directory / "MANIFEST.json").read_text(encoding="utf-8"))
    targets = {item["target"]: item for item in manifest["targets"]}
    invariant_checks = {
        "identity": imported_v2.creation.creation_id == imported_v1.creation.creation_id,
        "constraints": imported_v2.creation.content["identity"] == imported_v1.creation.content["identity"],
        "capabilities": imported_v2.creation.capabilities == imported_v1.creation.capabilities,
        "provenance": bool(manifest["provenance_root"]),
        "source_t": (clean_root / "source.t").is_file(),
    }
    checks = {
        "all_promised_targets_supported": all(item["supported"] for item in targets.values()),
        "clean_cli": clean["cli"]["returncode"] == 0 and json.loads(str(clean["cli"]["stdout"]))["result"] == "resposta externa Casulo",
        "clean_api": clean["api_health"] == {"effects": "simulation-only", "ok": True},
        "clean_service": clean["service_stopped"] is True,
        "clean_desktop_web": clean["desktop"]["served"] is True and "script-src 'none'" in str(clean["desktop"]["csp"]),
        "no_repo_pythonpath_or_cache": clean["pythonpath_present"] is False and clean["repo_in_cwd"] is False,
        "critical_round_trip_invariants": all(invariant_checks.values()),
        "real_effects_zero": manifest["real_effects_included"] is False,
        "secret_slots_empty": manifest["secret_slots"] == [],
        "validated_equals_published": sha(receipt_v2.archive) == receipt_v2.archive_sha256,
        "previous_version_recoverable": receipt_v1.archive.is_file() and MaterializedPackageImporter().import_archive(receipt_v1.archive).creation.version == 1,
        "signatures_verified": all(item["verified"] for item in signatures),
        "tcap_valid": parse_tcap(tcap).manifest["target"] == "python-hosted",
    }
    report = {
        "schema": "casulo.external-materialization-probe/1.0", "created_utc": datetime.now(timezone.utc).isoformat(),
        "state": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "invariants": invariant_checks,
        "targets": targets, "clean_environment": clean, "signatures": signatures,
        "v1": receipt_v1.to_dict(), "v2": receipt_v2.to_dict(),
        "tcap_sha256": hashlib.sha256(tcap).hexdigest(), "real_effects_executed": 0,
        "claim_boundary": "local external materialization product validation; not commercial signing or OS sandbox equivalence",
    }
    write_json(output / "external-materialization.json", report)
    print(json.dumps({"state": report["state"], "checks": checks, "v2_archive_sha256": receipt_v2.archive_sha256}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
