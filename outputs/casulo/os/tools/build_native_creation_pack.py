#!/usr/bin/env python3
"""Build the append-only NP10 T policies, artifact and eight-entry system pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from casulo.t.v2_tcap import TcapV2Builder, build_native_probe_bundle  # noqa: E402
from build_native_system_pack import KINDS, build, parse  # noqa: E402


OWNER = ROOT / "private/casulo-owner"
TOKEN_SOURCE = OWNER / "t-v2/native-creation-token-policy.t"
ARTIFACT_SOURCE = OWNER / "t-v2/native-creation-add.t"
ACCEPTANCE_SOURCE = OWNER / "t-v2/native-creation-acceptance.t"
PROMPT = OWNER / "native-creation-prompt.json"
MODEL_PROBE = ROOT / "release/casulo-native-qwen3-weight-formats-probe-v2.gguf"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bundle(source: Path, target: Path, module: str, function: str, payload: dict[str, object], surface: str):
    compiled = TcapV2Builder().build(
        (source,),
        target,
        entry_module=module,
        entry_function=function,
        tests={"properties": ["source_ir_identity", "deny_on_cancel", "runtime_evidence_before_decision"]},
        foreign_boundaries=(),
    )
    bundle = build_native_probe_bundle(
        compiled.directory,
        target.with_suffix(".bundle.json"),
        function_name=function,
        payload=payload,
        grants=(),
        surface_id=surface,
        scope_id="qwen3-4b:native-creation",
    )
    return compiled, bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Build NP10 creation system pack")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--system-pack", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    system_pack = args.system_pack.resolve()
    if ROOT.resolve() not in output_root.parents or ROOT.resolve() not in system_pack.parents:
        raise SystemExit("outputs must remain inside repository")
    if output_root.exists() or system_pack.exists():
        raise SystemExit("append-only output already exists")
    for required in (TOKEN_SOURCE, ARTIFACT_SOURCE, ACCEPTANCE_SOURCE, PROMPT, MODEL_PROBE):
        if not required.is_file():
            raise SystemExit(f"missing required source: {required}")
    output_root.mkdir(parents=True)

    prompt_payload = json.loads(PROMPT.read_text(encoding="utf-8"))
    prompt_sha = sha(PROMPT)
    token, token_bundle = build_bundle(
        TOKEN_SOURCE,
        output_root / "token-policy.tcap",
        "owner.native.creation_token_policy",
        "decide",
        {
            "decoder_gate": True, "token_index": 0, "max_tokens": 40,
            "input_token_id": prompt_payload["prompt_token_ids"][-1],
            "logits_sha256": "0" * 64, "blocks_completed": 36,
            "greedy_candidate_id": 45, "candidate_unpublished": True,
            "model_sha256": prompt_payload["model_sha256"], "prompt_sha256": prompt_sha,
            "policy_id": "greedy-creation-v1", "previous_receipt_hash": "0" * 64,
            "cancelled": False,
        },
        "native_creation_token_publication",
    )
    artifact, artifact_bundle = build_bundle(
        ARTIFACT_SOURCE,
        output_root / "creation-artifact.tcap",
        "owner.generated.some_dois_numeros",
        "execute",
        {"left": 7, "right": 11, "cancelled": False},
        "native_creation_simulation",
    )
    acceptance, acceptance_bundle = build_bundle(
        ACCEPTANCE_SOURCE,
        output_root / "acceptance-policy.tcap",
        "owner.native.creation_acceptance",
        "decide",
        {
            "model_output_valid": True, "creation_name": "SomeDoisNumeros",
            "function_name": "SomeDoisNumeros", "input_contract": "numero1,numero2",
            "output_contract": "resultado.", "generated_t_source_sha256": sha(ARTIFACT_SOURCE),
            "compiled_t_source_sha256": sha(ARTIFACT_SOURCE), "artifact_tcap_hash": artifact.tcap_hash,
            "simulation_status": "PASS", "simulation_left": 7, "simulation_right": 11,
            "simulation_result": 18, "expected_result": 18, "effects_requested": 0,
            "materialization_hash": "0" * 64, "cancelled": False,
        },
        "native_creation_materialization",
    )

    sources = (
        ("BOOTSTRAP_TCAP", ROOT / "release/FloodSurrogate.tcap"),
        ("UX_CONTRACT", ROOT / "schemas/product/hosted-native-ux-contract-v1.json"),
        ("GUIDE_T_SOURCE", ROOT / "examples/t/revolution/agent_logic.t"),
        ("MODEL_GGUF_PROBE", MODEL_PROBE),
        ("NATIVE_SAMPLING_POLICY", token_bundle),
        ("NATIVE_CREATION_PROMPT", PROMPT),
        ("NATIVE_CREATION_ARTIFACT", artifact_bundle),
        ("NATIVE_CREATION_ACCEPTANCE", acceptance_bundle),
    )
    blob = build([(KINDS[name], path.read_bytes()) for name, path in sources])
    parsed = parse(blob)
    system_pack.parent.mkdir(parents=True, exist_ok=True)
    system_pack.write_bytes(blob)
    record = {
        "schema": "casulo-native-creation-system-pack/1.0",
        "file": system_pack.relative_to(ROOT).as_posix(),
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "entries": [
            {"name": name, "kind": KINDS[name], "source": path.relative_to(ROOT).as_posix(),
             "source_sha256": sha(path), **parsed[index]}
            for index, (name, path) in enumerate(sources)
        ],
        "policies": {
            "token": {"tcap_hash": token.tcap_hash, "source_sha256": sha(TOKEN_SOURCE)},
            "artifact": {"tcap_hash": artifact.tcap_hash, "source_sha256": sha(ARTIFACT_SOURCE)},
            "acceptance": {"tcap_hash": acceptance.tcap_hash, "source_sha256": sha(ACCEPTANCE_SOURCE)},
        },
        "prompt_sha256": prompt_sha,
        "model_embedded": False,
        "network": False,
        "external_api": False,
        "physical_device_written": False,
        "compilation_cache_contract": "live generated T source must match compiled source hash before execution",
    }
    manifest = system_pack.with_suffix(system_pack.suffix + ".manifest.json")
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    system_pack.with_suffix(system_pack.suffix + ".sha256").write_text(
        f"{record['sha256']}  {system_pack.name}\n", encoding="ascii"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
