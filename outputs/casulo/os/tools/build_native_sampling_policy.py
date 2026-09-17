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


SOURCE = ROOT / "private/casulo-owner/t-v2/native-sampling-policy.t"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the owner-only incremental T sampling policy and Native system pack")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--system-pack", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    system_pack = args.system_pack.resolve()
    if ROOT.resolve() not in output_root.parents or ROOT.resolve() not in system_pack.parents:
        raise SystemExit("outputs must remain inside repository")
    if output_root.exists() or system_pack.exists():
        raise SystemExit("append-only output already exists")
    output_root.mkdir(parents=True)

    built = TcapV2Builder().build(
        (SOURCE,),
        output_root / "native-sampling-policy.tcap",
        entry_module="owner.native.sampling_policy",
        entry_function="decide",
        tests={
            "properties": [
                "decoder_required",
                "per_token_exact_logits_identity",
                "receipt_chain_required",
                "late_publication_denied",
                "cancellation_fail_closed",
            ]
        },
        foreign_boundaries=(
            {
                "name": "qwen3_greedy_candidate",
                "kind": "foreign_primitive",
                "decision_authority": False,
            },
        ),
    )
    bundle = build_native_probe_bundle(
        built.directory,
        output_root / "native-sampling-policy.bundle.json",
        function_name="decide",
        payload={
            "decoder_gate": True,
            "token_index": 0,
            "input_token_id": 49242,
            "logits_sha256": "4760c2d93598f80a1b3b44cdbcb20fe4785af71127c6fe544c2996c07035a509",
            "blocks_completed": 36,
            "greedy_candidate_id": 6237,
            "candidate_unpublished": True,
            "policy_id": "greedy-incremental-v1",
            "previous_receipt_hash": "0" * 64,
            "cancelled": False,
        },
        grants=(),
        surface_id="native_sampling_publication",
        scope_id="qwen3-4b:incremental-token",
    )

    sources = (
        ("BOOTSTRAP_TCAP", ROOT / "release/FloodSurrogate.tcap"),
        ("UX_CONTRACT", ROOT / "schemas/product/hosted-native-ux-contract-v1.json"),
        ("GUIDE_T_SOURCE", ROOT / "examples/t/revolution/agent_logic.t"),
        ("MODEL_GGUF_PROBE", ROOT / "release/casulo-native-qwen3-weight-formats-probe-v2.gguf"),
        ("NATIVE_SAMPLING_POLICY", bundle),
    )
    blob = build([(KINDS[name], path.read_bytes()) for name, path in sources])
    parsed = parse(blob)
    system_pack.parent.mkdir(parents=True, exist_ok=True)
    system_pack.write_bytes(blob)
    manifest = {
        "schema": "casulo-native-system-pack/1.0",
        "file": system_pack.relative_to(ROOT).as_posix(),
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "entries": [
            {
                "name": name,
                "kind": KINDS[name],
                "source": path.relative_to(ROOT).as_posix(),
                "source_sha256": sha(path),
                **parsed[index],
            }
            for index, (name, path) in enumerate(sources)
        ],
        "t_sampling_policy": {
            "source": SOURCE.relative_to(ROOT).as_posix(),
            "source_sha256": sha(SOURCE),
            "tcap_hash": built.tcap_hash,
            "bundle_sha256": sha(bundle),
            "policy_id": "greedy-incremental-v1",
            "decision_authority": True,
            "runtime_payload": True,
            "receipt_chained": True,
        },
        "model_embedded": False,
        "network": False,
        "physical_device_written": False,
    }
    manifest_path = system_pack.with_suffix(system_pack.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    system_pack.with_suffix(system_pack.suffix + ".sha256").write_text(
        f"{manifest['sha256']}  {system_pack.name}\n", encoding="ascii"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
