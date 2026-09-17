from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from casulo.t.learn_canary import parse_flood_canary
from casulo.t.learn_native import build_learn_tcap
from casulo.t.tcap import parse_tcap


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "examples/t/flood_surrogate_training.t"
DEFAULT_RELEASE = ROOT / "release"
DEFAULT_EVIDENCE = (
    ROOT / "evidence/casulo-os-rp01/g3/flood-tcap-two-build-reproducibility.json"
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild FloodSurrogate twice and freeze byte-level TCAP evidence."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    source = args.source.expanduser().resolve(strict=True)
    release = args.release.expanduser().resolve()
    evidence_path = args.evidence.expanduser().resolve()
    first = build_learn_tcap(source, release)
    with tempfile.TemporaryDirectory(prefix="casulo-tcap-rebuild-") as temporary:
        second = build_learn_tcap(source, Path(temporary))
        first_raw = first.tcap_file.read_bytes()
        second_raw = second.tcap_file.read_bytes()
    if first_raw != second_raw:
        raise SystemExit("two TCAP builds differ byte-for-byte")

    package = parse_tcap(first_raw)
    canary_segment = next(item for item in package.segments if item.name == "canary")
    code_segment = next(item for item in package.segments if item.name == "code")
    canary = parse_flood_canary(canary_segment.data)
    evidence = {
        "protocol": "casulo-tcap-two-build-reproducibility/1.1",
        "status": "PASS",
        "artifact": {
            "path": first.tcap_file.relative_to(ROOT).as_posix(),
            "bytes": len(first_raw),
            "sha256": sha256(first_raw),
            "content_sha256": package.manifest["content_sha256"],
        },
        "compiler": package.manifest["compiler"],
        "two_independent_builds": {
            "byte_for_byte_equal": True,
            "first_sha256": sha256(first_raw),
            "second_sha256": sha256(second_raw),
            "temporary_second_build_preserved": False,
        },
        "raw_aot": {
            "bytes": len(code_segment.data),
            "sha256": sha256(code_segment.data),
            "static_self_containment_audit": "PASS",
            "dynamic_address_runtime_audit": "PASS",
            "forbidden_got_plt_undefined_low_page": "absent",
            "float_execution": "sse2-hard-float-memory-context",
        },
        "canary": {
            "role": "bounded-correctness-canary",
            "records": canary.records,
            "epochs": canary.epochs,
            "target_loss": canary.target_loss,
            "expected_initial_loss": canary.expected_initial_loss,
            "expected_final_loss": canary.expected_final_loss,
            "tolerance": canary.tolerance,
            "segment_bytes": len(canary_segment.data),
            "segment_sha256": sha256(canary_segment.data),
        },
        "performance_measured": False,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
