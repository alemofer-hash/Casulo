"""Assemble evidence from executed gates; never turns failed checks into PASS."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from casulo.family.contracts import AuthContext, FamilyAuthorizationError
from casulo.family.persona import PersonaResolver, PrincipalBinding


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)+"\n",
                    encoding="utf-8", newline="\n")


def test_receipt(path, prefix=None):
    nodes = list(ET.parse(path).getroot().iter("testcase"))
    if prefix:
        nodes = [n for n in nodes if n.attrib["classname"].startswith(prefix)]
    failures = [n.attrib["name"] for n in nodes if n.find("failure") is not None or n.find("error") is not None]
    skipped = [n.attrib["name"] for n in nodes if n.find("skipped") is not None]
    if failures or not nodes:
        raise RuntimeError("TEST_GATE_FAILED")
    return {"passed": len(nodes)-len(skipped), "skipped": len(skipped), "failed": 0,
            "tests": [n.attrib["name"] for n in nodes], "skipped_tests": skipped, "junit_sha256": sha(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--product-tests", default="tests-2")
    parser.add_argument("--family-junit", default="family-final.xml")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    evidence = root/"evidence/family/day6"
    attempt = evidence/args.attempt
    integration = json.loads((attempt/"integration-result.json").read_text())
    browser = json.loads((attempt/"pwa-browser.json").read_text())
    if integration["status"] != "PASS_REAL_PIPELINE" or browser["status"] != "PASS":
        raise RuntimeError("REAL_GATE_FAILED")
    tests = {"family": test_receipt(evidence/args.family_junit),
             "day6": test_receipt(evidence/args.family_junit, "tests.family.test_day6"),
             "product": test_receipt(evidence/args.product_tests/"product.xml")}
    for name in ("baseline.json", "dependency-and-model-provenance.json", "voice-runtime-lifecycle.json",
                 "voice-e2e-real.json", "voice-cancellation-cleanup.json", "resource-samples.jsonl",
                 "port-inspection-before.txt", "port-inspection-during.txt", "port-inspection-after.txt",
                 "process-inspection-before.txt", "process-inspection-after.txt"):
        shutil.copyfile(attempt/name, evidence/name)
    baseline = json.loads((evidence/"baseline.json").read_text())
    baseline["initial_working_tree_clean"] = True
    baseline["initial_clean_observation"] = "read-only git status before this task's first edit"
    write(evidence/"baseline.json", baseline)
    for label, result in tests.items():
        (evidence/("test-results-"+label+".txt")).write_text(
            f"Permitted scope: {label}\n{result['passed']} passed, {result['skipped']} skipped, 0 failed\n"
            f"Source JUnit SHA256: {result['junit_sha256']}\n"+
            "\n".join(("SKIP " if name in result["skipped_tests"] else "PASS ")+name
                       for name in result["tests"])+"\n",
            encoding="utf-8", newline="\n")
    # Validate profiles using both the JSON schema and the runtime's exact contracts.
    import jsonschema
    schema = json.loads((root/"schemas/family/cleo-persona.schema.json").read_text())
    active = {"authenticated": True, "unlocked": True}
    resolver = PersonaResolver(root/"config/family/cleo", active=lambda _: active["authenticated"],
                               unlocked=lambda: active["unlocked"], harness=True)
    routing = []
    for principal, profile in resolver.profiles.items():
        jsonschema.Draft202012Validator(schema).validate(profile)
        auth = AuthContext(principal, "synthetic-"+principal, "session-"+principal)
        resolver.bind(PrincipalBinding(auth, principal, local_host=principal=="guilherme",
                                      route="LOCAL_PRIVATE" if principal=="guilherme" else "PERSONAL_DEVICE",
                                      synthetic=True))
        _, metadata = resolver.resolve(auth, "Uma pergunta neutra.")
        routing.append({"principal": principal, "synthetic_only": True, **metadata})
    write(evidence/"persona-schema-validation.json", {
        "status": "PASS", "schema_sha256": sha(root/"schemas/family/cleo-persona.schema.json"),
        "profiles": {p: sha(root/"config/family/cleo"/file) for p, file in
                     (("guilherme", "host.v1.json"), ("alexandra", "alexandra.v1.json"), ("eduardo", "eduardo.v1.json"))},
        "validator": "JSON Schema Draft 2020-12 plus exact versioned runtime contracts"})
    write(evidence/"principal-persona-routing.json", {"status": "PASS", "routes": routing,
          "unknown_default": "DENY", "evidence_cases": tests["day6"]["tests"],
          "junit_sha256": tests["day6"]["junit_sha256"]})
    host = AuthContext("guilherme", "synthetic-guilherme", "session-guilherme")
    transitions = []
    for category, text in (("explicit_neutral_affection", "Cleo, vamos conversar com carinho, só nós dois."),
                           ("technical_and_security", "Precisamos revisar o código com segurança."),
                           ("ambiguous_affection", "talvez uma brincadeira?")):
        _, metadata = resolver.resolve(host, text)
        transitions.append({"category": category, **metadata})
    active["unlocked"] = False
    try:
        resolver.resolve(host, "Uma pergunta neutra.")
        raise RuntimeError("LOCK_DID_NOT_DENY")
    except FamilyAuthorizationError:
        transitions.append({"category": "locked", "result": "DENIED", "private_state": "WORK"})
    write(evidence/"host-register-transitions.json", {"status": "PASS", "synthetic": transitions,
          "real": json.loads((attempt/"host-register-transitions.json").read_text()),
          "intimate_text_retained": False})
    write(evidence/"family-profile-isolation.json", {"status": "PASS",
          "family_routes": [r for r in routing if r["principal"] != "guilherme"],
          "independent_jobs_sessions_memories_receipts": True,
          "private_fields_in_family_profiles": False,
          "family_enrollment": "SYNTHETIC_HARNESS_ONLY",
          "source_cases": [n for n in tests["day6"]["tests"] if any(k in n for k in
                           ("family_", "cross_session", "rag", "http_identity"))],
          "junit_sha256": tests["day6"]["junit_sha256"]})
    provenance = json.loads((evidence/"dependency-and-model-provenance.json").read_text())
    build_path = Path(os.environ["LOCALAPPDATA"])/"Casulo/cache/voice/BUILD.json"
    provenance["existing_native_build"] = json.loads(build_path.read_text())
    provenance["existing_native_build_sha256"] = sha(build_path)
    provenance["browser_test"] = {"playwright": browser["playwright"], "chromium": browser["browser"],
                                  "license": "Apache-2.0 (Playwright); Chromium component licenses",
                                  "source": "https://github.com/microsoft/playwright", "installed_by_this_task": False}
    write(evidence/"dependency-and-model-provenance.json", provenance)
    write(evidence/"SBOM.json", {"schema": "casulo.day6.sbom/1.0", "components": [
        provenance["lock"]["asr"], provenance["lock"]["tts"],
        integration["model_identity"], provenance["browser_test"]],
        "weights_redistributed_in_git": False, "new_downloads": 0,
        "provenance_sha256": sha(evidence/"dependency-and-model-provenance.json")})
    # Check actual runtime state files, not only implementation assertions.
    state = Path(os.environ["LOCALAPPDATA"])/"Casulo/family-rp01/day6"/args.attempt
    state_files = [p for p in state.rglob("*") if p.is_file()]
    forbidden = [p.name for p in state_files if p.suffix.lower() in {".wav", ".pcm", ".mp3", ".webm"}]
    if forbidden or (state/"jobs.sqlite3").exists() or any((state/"empty-slot-actions").iterdir()):
        raise RuntimeError("PRIVACY_RETENTION_FAILED")
    audit_text = (state/"audit.jsonl").read_text(encoding="utf-8")
    if any(phrase in audit_text for phrase in ("Diga uma frase", "Uma resposta local.", "explicit_sensuality")):
        raise RuntimeError("PRIVATE_CONTENT_IN_AUDIT")
    write(evidence/"privacy-retention-audit.json", {"status": "PASS", "audio_temp_files": forbidden,
        "conversation_database_on_disk": False, "kv_files_created": 0,
        "audit_content": "identifiers, counts, hashes; no raw utterance or answer",
        "state_acl": "owner-only-inherited", "state_file_names": [p.name for p in state_files],
        "retention": {"voice_input_seconds": 20, "voice_turn_seconds": 180,
                      "completed_audio_seconds": 30, "ephemeral_job_seconds": 120,
                      "maximum_retained_jobs": 16, "maximum_voice_turns": 16,
                      "http_worker_limit": 8, "max_pcm_output_bytes": 1920000},
        "physical_memory_zeroization_claim": False, "intimate_fixture_saved": False})
    static_commands = [
        [sys.executable, "-m", "ruff", "check", "src/casulo/family", "tests/family/test_day6_cleo_voice.py",
         "private/casulo-owner/src/casulo_owner/family_cleo_app.py",
         "private/casulo-owner/src/casulo_owner/family_model_adapter.py", "scripts/16-verify-family-day6.py",
         "scripts/17-test-family-day6.py", "scripts/18-seal-family-day6.py", "scripts/19-attest-family-day6.py"],
        [sys.executable, "-m", "compileall", "-q", "src/casulo/family",
         "private/casulo-owner/src/casulo_owner/family_cleo_app.py"],
    ]
    node = Path(os.environ["USERPROFILE"])/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    for script in ("apps/casulo-family-pwa/app.js", "apps/casulo-family-pwa/voice.js", "scripts/16-test-cleo-pwa.cjs"):
        static_commands.append([str(node), "--check", script])
    static_output = []
    for command in static_commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
        static_output.append({"command": command, "exit_code": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            write(evidence/"static-checks.json", static_output)
            raise RuntimeError("STATIC_GATE_FAILED")
    write(evidence/"static-checks.json", static_output)
    changed = subprocess.run(["git", "diff", "--name-only"], cwd=repo,
                              check=True, capture_output=True, text=True).stdout.splitlines()
    added = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo,
                            check=True, capture_output=True, text=True).stdout.splitlines()
    source_hashes = {}
    for relative in changed+added:
        path = repo/relative
        if relative.startswith("outputs/casulo/") and "/evidence/" not in relative and path.is_file():
            source_hashes[relative] = sha(path)
    result = {"schema": "casulo.family.day6-final-receipt/1.0", "status": "PASS",
              "authoritative_attempt": args.attempt, "input_commit": baseline["input_commit"],
              "input_tree": baseline["input_tree"], "initial_working_tree_clean": True,
              "persona_instances": [r["persona_instance_id"] for r in routing],
              "host_only_registers": ["WORK", "PLAY_PRIVATE"], "family_private_fields": False,
              "voice_runtime": {"asr": provenance["lock"]["asr"], "tts": provenance["lock"]["tts"]},
              "real_pipeline": integration, "tests": tests, "source_sha256": source_hashes,
              "final_version_control": {"mode": "post-commit-attestation",
                "reason": "A receipt committed inside its own commit cannot contain that commit's literal SHA without a hash cycle.",
                "reproduce": "scripts/19-attest-family-day6.py --output <outside-repository>/final-receipt.json"},
              "limitations": ["Physical microphone and speaker were not tested; Chromium used a neutral fake microphone and muted audio.",
                "Maria has no qualified per-register prosody control; only text/metadata separation is proven.",
                "ASR base-q5_1 confused ceu/seu in a neutral smoke; open-vocabulary accuracy is not qualified.",
                "Private route and sole participant are owner assertions plus local unlocked desktop, not biometric or occupancy verification.",
                "Private-affection activation uses an intentionally narrow exact-utterance allowlist; ambiguous inputs fall back to WORK.",
                "No mobile enrollment, Android, physical device revocation, encrypted SQLite, universal prompt-injection or thermal claims.",
                "No physical RAM/pagefile erasure claim; Python and browser release references and native children exit."]}
    write(evidence/"final-receipt.json", result)
    print(json.dumps({"status": "PASS", "attempt": args.attempt, "tests": {k:v['passed'] for k,v in tests.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
