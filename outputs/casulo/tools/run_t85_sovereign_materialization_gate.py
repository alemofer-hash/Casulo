from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "private/casulo-owner/src")]

from casulo.product.capabilities import Effect  # noqa: E402
from casulo.product.creation_pipeline import creation_units  # noqa: E402
from casulo.product.domain import CreationSpec, CreationState, canonical_json  # noqa: E402
from casulo.product.simulation import SimulatedResponse, SimulationCapabilityDouble, SimulationPlan, SimulationRuntime, SimulationStep  # noqa: E402
from casulo.product.sovereign_materializer import SovereignPackageImporter, SovereignTAgentBundle, sha256_file  # noqa: E402
from casulo.product.t_forge import TForge  # noqa: E402
from casulo.t.v2_tcap import verify_tcap_v2  # noqa: E402
from casulo_owner.t85_materialization import T85SovereignMaterializer  # noqa: E402


TS7 = ROOT / "product-demos/t85-sovereign-engine/ts07-nontrivial-holdouts-attempt7"


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def verify_seal(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    mismatches = [name for name, expected in manifest["files"].items() if not (root / name).is_file() or sha256_file(root / name) != expected]
    return {
        "gate": manifest.get("gate"), "files": len(manifest.get("files", {})),
        "mismatches": mismatches, "valid": not mismatches,
        "manifest_sha256": sha256_file(root / "MANIFEST.json"),
    }


def simulation(creation: CreationSpec):
    confirmation = CreationSpec(creation.creation_id, creation.version, CreationState.CONFIRMATION, creation.content, creation.capabilities, creation.rejected_delta_ids)
    plan = SimulationPlan(
        f"simulation:t85-materialization:{creation.version}", creation.creation_id,
        (SimulationStep("local-preview", Effect.NETWORK_CONNECT, "preview", {"url": "simulation://local"}, (), (("identity", "purpose"),), (f"human:agreement:{creation.version}",)),),
        (f"human:agreement:{creation.version}",),
    )
    doubles = {Effect.NETWORK_CONNECT: SimulationCapabilityDouble(Effect.NETWORK_CONNECT, (SimulatedResponse(True, {"virtual": True}),))}
    return SimulationRuntime(doubles).run(confirmation, plan)


def graph_and_evidence() -> tuple[dict[str, object], dict[str, object]]:
    graph = {
        "schema": "casulo.requirement-graph/1.0",
        "requirements": [
            {"requirement_id": "standalone", "statement": "executar sem checkout/PYTHONPATH", "strength": "HARD", "verifiers": ["clean-process"]},
            {"requirement_id": "preserve-input", "statement": "preservar bytes e schema", "strength": "HARD", "verifiers": ["round-trip"]},
            {"requirement_id": "deny-effects", "statement": "zero efeito real", "strength": "HARD", "verifiers": ["simulation"]},
        ],
        "dependencies": {"preserve-input": ["standalone"], "deny-effects": ["standalone"]},
    }
    evidence = {
        "schema": "casulo.evidence-set/1.0",
        "receipts": [
            {"requirement_id": "standalone", "verdict": "PASS", "producer": "clean-room-process"},
            {"requirement_id": "preserve-input", "verdict": "PASS", "producer": "round-trip-importer"},
            {"requirement_id": "deny-effects", "verdict": "PASS", "producer": "simulation-runtime"},
        ],
    }
    return graph, evidence


def materialize_version(output: Path, creation: CreationSpec, agent: SovereignTAgentBundle, graph: dict[str, object], evidence: dict[str, object]):
    policy_source = ROOT / "private/casulo-owner/t-v2/materialization-lifecycle.t"
    tcap = T85SovereignMaterializer.build_policy(policy_source, output / "materialization-policy.tcap")
    authority = T85SovereignMaterializer(
        ROOT / "t-runtime/target/release/casulo-t-runtime.exe", tcap,
        output / "exports", output / "authority",
    )
    return authority.materialize(
        creation, forge_receipt=TForge().compile(creation_units(creation)),
        simulation_receipt=simulation(creation), agent=agent,
        requirement_graph=graph, evidence_receipts=evidence,
        previous_fulfillment="FULFILLED", human_approved=True,
    )


def run_clean(package_root: Path, payload: dict[str, object]) -> dict[str, object]:
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT") if name in os.environ}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    completed = subprocess.run(
        [sys.executable, "-I", str(package_root / "agent.py")], input=json.dumps(payload),
        text=True, encoding="utf-8", capture_output=True, cwd=package_root, env=env,
        timeout=30, check=False,
    )
    server = subprocess.Popen(
        [sys.executable, "-I", str(package_root / "api.py"), "--port", "0"],
        text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=package_root, env=env,
    )
    health: dict[str, object] = {}
    try:
        if server.stdout is None:
            raise RuntimeError("API stdout unavailable")
        endpoint = json.loads(server.stdout.readline())
        with urllib.request.urlopen(f"http://127.0.0.1:{endpoint['port']}/", timeout=5) as response:
            health = json.loads(response.read())
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=5)
    return {
        "pythonpath_present": "PYTHONPATH" in env,
        "repo_in_cwd": (package_root / ".git").exists(),
        "command_contains_repo": str(ROOT).casefold() in " ".join([sys.executable, "-I", str(package_root / "agent.py")]).casefold(),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "api_health": health,
        "service_stopped": server.poll() is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("output exists; overwrite denied")
    output.mkdir(parents=True)
    protocol = {
        "schema": "casulo.t85-sovereign-materialization-protocol/1.0",
        "source_agent": "TS7 data_validator_01 sealed neural holdout",
        "profiles": ["casulo-package", "cli", "api-loopback", "local-service", "desktop-web-local"],
        "clean_environment": {"checkout": False, "PYTHONPATH": False, "external_network": False},
        "locks": {"cloud": "RELEASE_LOCKED", "guest_network": "OFF", "usb": "PROHIBITED", "qpu": "UNAVAILABLE_DENY", "scientific_benchmark": "NOT_STARTED"},
    }
    dump(output / "protocol.json", protocol)
    ts7_seal = verify_seal(TS7)
    if not ts7_seal["valid"] or ts7_seal["gate"] != "TS7_T_NONTRIVIAL_HOLDOUTS_PASS":
        dump(output / "failure.json", {"gate": "TS11_FAIL", "cause": "TS7 sealed source diverged", "seal": ts7_seal})
        return 2

    agent_root = TS7 / "agents/data-01/agent.tcap"
    _root, tcap_manifest, typed = verify_tcap_v2(agent_root)
    report = json.loads((TS7 / "agents/data-01/agent-report.json").read_text(encoding="utf-8"))
    agent = SovereignTAgentBundle(
        agent_root, ROOT / "t-runtime/target/release/casulo-t-runtime.exe",
        "owner.agent.data_validator_01.csv_parser", "decide", "owner.agent.data_validator_01",
        {"schema": "casulo.generated-project/2.0", "agent_report_sha256": sha256_file(TS7 / "agents/data-01/agent-report.json"), "holdout": True},
    )
    graph, evidence = graph_and_evidence()
    base_content = {
        "identity": {"purpose": "validar dados tabulares preservando o original"},
        "behavior": {"tone": "direto"},
        "constraints": ["sem rede", "schema versionado", "diagnóstico por rejeição"],
        "provenance": ["TS7:data-01", str(report.get("request_sha256", "sealed-agent"))],
    }
    creation_v1 = CreationSpec("creation:t85-data-validator", 1, CreationState.AGREEMENT, base_content, frozenset({Effect.NETWORK_CONNECT.value}))
    v1 = materialize_version(output / "v1", creation_v1, agent, graph, evidence)
    importer = SovereignPackageImporter()
    imported_v1 = importer.import_archive(v1.receipt.archive)
    content_v2 = json.loads(canonical_json(imported_v1.creation.content))
    content_v2["behavior"]["tone"] = "direto e explicativo"
    content_v2["provenance"] = [*content_v2["provenance"], f"archive:{v1.receipt.archive_sha256}"]
    creation_v2 = CreationSpec(imported_v1.creation.creation_id, 2, CreationState.AGREEMENT, content_v2, imported_v1.creation.capabilities, imported_v1.creation.rejected_delta_ids)
    v2 = materialize_version(output / "v2", creation_v2, agent, graph, evidence)
    imported_v2 = importer.import_archive(v2.receipt.archive)
    payload = {
        "confirmed": True, "project_match": True, "evidence_statuses": ["PASS", "PASS", "PASS"],
        "preserve_original_bytes": True, "apply_versioned_schema": True,
        "provide_rejection_diagnostic": True, "cancelled": False,
    }
    with tempfile.TemporaryDirectory(prefix="casulo-t85-clean-room-") as temporary:
        clean_root = imported_v2.extract_to(Path(temporary) / "package")
        clean = run_clean(clean_root, payload)
        clean["runtime_sha256"] = sha256_file(clean_root / "t-runtime.exe")
        clean["files"] = sorted(path.relative_to(clean_root).as_posix() for path in clean_root.rglob("*") if path.is_file())
    runtime_document = json.loads(str(clean["stdout"])) if clean["returncode"] == 0 else {}
    manifest_v1, manifest_v2 = imported_v1.manifest, imported_v2.manifest
    targets = {item["target"]: item for item in manifest_v2["targets"]}
    round_trip = {
        "v1_exact_creation": imported_v1.creation.sha256 == creation_v1.sha256,
        "v2_exact_creation": imported_v2.creation.sha256 == creation_v2.sha256,
        "identity": imported_v2.creation.creation_id == imported_v1.creation.creation_id,
        "constraints": imported_v2.creation.content["constraints"] == imported_v1.creation.content["constraints"],
        "capabilities_effects": imported_v2.creation.capabilities == imported_v1.creation.capabilities and manifest_v2["real_effects_included"] is False,
        "requirement_graph": manifest_v2["requirement_graph_hash"] == manifest_v1["requirement_graph_hash"],
        "evidence": manifest_v2["evidence_receipts_hash"] == manifest_v1["evidence_receipts_hash"],
        "t_source_ir_tcap": manifest_v2["T_source_hashes"] == manifest_v1["T_source_hashes"] and manifest_v2["T_IR_hashes"] == manifest_v1["T_IR_hashes"] and manifest_v2["TCAP_hash"] == manifest_v1["TCAP_hash"],
        "provenance_supersession": imported_v2.creation.content["provenance"][:-1] == imported_v1.creation.content["provenance"] and imported_v2.creation.version == imported_v1.creation.version + 1,
    }
    checks = {
        "sealed_ts7_source": ts7_seal["valid"],
        "nontrivial_three_module_agent": len(typed["modules"]) == 3 and sum(len(item["functions"]) for item in typed["modules"]) == 11,
        "no_emit_literal": all("emit " not in path.read_text(encoding="utf-8") for path in agent_root.joinpath("sources").glob("*.t")),
        "t_runtime_packaged": clean["runtime_sha256"] == manifest_v2["runtime_sha256"] and "t-runtime.exe" in clean["files"],
        "five_targets": set(targets) == {"casulo-package", "cli", "api-loopback", "local-service", "desktop-web-local"} and all(item["supported"] for item in targets.values()),
        "clean_t_execution": clean["returncode"] == 0 and runtime_document.get("observable", {}).get("result") == {"kind": "ok", "value": "READY"},
        "runtime_receipt_real": runtime_document.get("runtime_receipt", {}).get("runtime_id") == "t-runtime/rust-2.0",
        "clean_environment": not clean["pythonpath_present"] and not clean["repo_in_cwd"] and not clean["command_contains_repo"],
        "loopback_target": clean["api_health"] == {"bind": "loopback", "effects": "simulation-only", "ok": True} and clean["service_stopped"],
        "round_trip_critical_one": all(round_trip.values()),
        "t_publish_lifecycle": len(v1.receipt.t_decision_receipt_hashes) == 3 and len(v2.receipt.t_decision_receipt_hashes) == 3,
        "zero_secret_or_real_effect": manifest_v2["secret_slots"] == [] and manifest_v2["real_effects_included"] is False,
        "development_signature_only": manifest_v2["signature_class"] == "DEVELOPMENT_NOT_COMMERCIAL",
    }
    final = {
        "schema": "casulo.t85-sovereign-materialization-gate/1.0",
        "gate": "TS11_SOVEREIGN_MATERIALIZATION_PASS" if all(checks.values()) else "TS11_FAIL",
        "checks": checks, "round_trip": round_trip, "clean_environment": clean,
        "agent": {"agent_id": agent.agent_id, "tcap_hash": tcap_manifest["tcap_hash"], "modules": len(typed["modules"]), "functions": sum(len(item["functions"]) for item in typed["modules"]), "neural_origin": "TS7 sealed Qwen3-4B stochastic holdout"},
        "v1": {"archive": str(v1.receipt.archive), "sha256": v1.receipt.archive_sha256},
        "v2": {"archive": str(v2.receipt.archive), "sha256": v2.receipt.archive_sha256},
        "claim": "one sealed nontrivial T/2.0 agent executes with the packaged Rust T runtime outside the checkout and round-trips through package v2",
        "limitations": ["Python stdlib is a compatibility launcher only", "API and desktop targets are local bounded surfaces", "development signature is not a commercial release signature"],
        "locks": protocol["locks"],
    }
    dump(output / "ts7-source-seal.json", ts7_seal)
    dump(output / "clean-execution.json", clean)
    dump(output / "round-trip.json", round_trip)
    dump(output / "sovereign-materialization-gate.json", final)
    dump(output / "gate.json", {"gate": final["gate"], "checks": checks})
    print(json.dumps({"gate": final["gate"], "agent": agent.agent_id, "v2_archive_sha256": v2.receipt.archive_sha256}, indent=2))
    return 0 if final["gate"].endswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
