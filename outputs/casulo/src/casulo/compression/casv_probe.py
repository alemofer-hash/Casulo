from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .casv_archive import pack_casv_frames
from .casv_ir import CanonicalVideoSpec
from .independent_casv import reconstruct_casv_independently


class CASVProbeError(RuntimeError):
    pass


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _draw_rectangle(
    frame: bytearray,
    spec: CanonicalVideoSpec,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    color: bytes,
) -> None:
    row = color * width
    for offset_y in range(height):
        start = ((y + offset_y) * spec.width + x) * 3
        frame[start : start + len(row)] = row


def make_structured_probe_video(spec: CanonicalVideoSpec) -> bytes:
    if spec.width < 64 or spec.height < 36 or spec.frame_count > 32:
        raise CASVProbeError("structured probe requires >=64x36 and at most 32 frames")
    background = bytes((9, 15, 28))
    frames = bytearray()
    for frame_index in range(spec.frame_count):
        frame = bytearray(background * (spec.width * spec.height))
        _draw_rectangle(
            frame,
            spec,
            x=4 + frame_index,
            y=6,
            width=12,
            height=8,
            color=bytes((232, 157, 61)),
        )
        _draw_rectangle(
            frame,
            spec,
            x=spec.width - 20,
            y=spec.height - 12,
            width=14,
            height=6,
            color=bytes((32, 111, 174)),
        )
        frames.extend(frame)
    return bytes(frames)


def make_noise_probe_video(spec: CanonicalVideoSpec) -> bytes:
    blocks: list[bytes] = []
    produced = 0
    counter = 0
    while produced < spec.expected_bytes:
        block = hashlib.sha256(b"CASV-NOISE" + counter.to_bytes(8, "big")).digest()
        blocks.append(block)
        produced += len(block)
        counter += 1
    return b"".join(blocks)[: spec.expected_bytes]


def _seal_probe(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "PROBE_MANIFEST.json":
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    manifest_path = root / "PROBE_MANIFEST.json"
    manifest_path.write_bytes(
        _canonical_json(
            {
                "schema": "casulo.casv-probe-manifest/0.1",
                "entries": entries,
            }
        )
        + b"\n"
    )
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def run_casv_probe(
    output: str | Path,
    *,
    default_policy: str | Path,
    force_raw_policy: str | Path,
    runtime: str | Path | None = None,
) -> dict[str, Any]:
    """Run a bounded synthetic validation; this is not an 8K or natural-video claim."""

    root = Path(output).resolve()
    if root.exists():
        raise CASVProbeError(f"probe directory already exists: {root}")
    root.mkdir(parents=True)
    spec = CanonicalVideoSpec(
        width=96,
        height=54,
        frame_count=24,
        fps_numerator=24,
    )
    structured = make_structured_probe_video(spec)
    noise = make_noise_probe_video(spec)
    sources = root / "sources"
    sources.mkdir()
    (sources / "structured.rgb").write_bytes(structured)
    (sources / "noise.rgb").write_bytes(noise)

    structured_default = pack_casv_frames(
        structured,
        spec,
        root / "structured.casv",
        evidence_dir=root / "structured-evidence",
        policy_source=default_policy,
        runtime=runtime,
        source_label="structured.rgb",
    )
    structured_raw = pack_casv_frames(
        structured,
        spec,
        root / "structured-force-raw.casv",
        evidence_dir=root / "structured-force-raw-evidence",
        policy_source=force_raw_policy,
        runtime=runtime,
        source_label="structured.rgb",
    )
    noise_default = pack_casv_frames(
        noise,
        spec,
        root / "noise.casv",
        evidence_dir=root / "noise-evidence",
        policy_source=default_policy,
        runtime=runtime,
        source_label="noise.rgb",
    )

    verifications = {
        "structured": reconstruct_casv_independently(root / "structured.casv"),
        "structured_force_raw": reconstruct_casv_independently(
            root / "structured-force-raw.casv"
        ),
        "noise": reconstruct_casv_independently(root / "noise.casv"),
    }
    causal_mutation = {
        "default_tcap_sha256": structured_default["authority"]["tcap_sha256"],
        "force_raw_tcap_sha256": structured_raw["authority"]["tcap_sha256"],
        "tcap_changed": structured_default["authority"]["tcap_sha256"]
        != structured_raw["authority"]["tcap_sha256"],
        "default_storage_mode": structured_default["storage_mode"],
        "force_raw_storage_mode": structured_raw["storage_mode"],
        "execution_changed": structured_default["storage_mode"]
        != structured_raw["storage_mode"],
        "canonical_output_preserved": verifications["structured"]["canonical_sha256"]
        == verifications["structured_force_raw"]["canonical_sha256"],
    }
    gates = {
        "native_format": all(
            not item["claims"]["contains_mp4_or_hevc_payload"]
            for item in (structured_default, structured_raw, noise_default)
        ),
        "independent_exact_roundtrip": all(
            item["status"] == "PASS" for item in verifications.values()
        ),
        "explicit_base_dynamics_residual": structured_default["storage_mode"]
        == "GENERATIVE_EXACT",
        "t_policy_mutation_is_causal": all(causal_mutation.values()),
        "structured_archive_smaller_than_canonical_rgb": structured_default[
            "archive_bytes"
        ]
        < len(structured),
        "noise_is_not_misreported_as_compressible": noise_default["cost_verdict"]
        == "REJECT",
    }
    report = {
        "schema": "casulo.casv-bounded-probe/0.1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "scientific_scope": "SYNTHETIC_ENGINEERING_VALIDATION_ONLY",
        "canonical_spec": spec.as_dict(),
        "structured": structured_default,
        "structured_force_raw": structured_raw,
        "noise": noise_default,
        "causal_mutation": causal_mutation,
        "verifications": verifications,
        "gates": gates,
        "claim_boundary": {
            "proven": [
                "custom CASV container executes a deterministic visual program",
                "independent exact RGB8 reconstruction",
                "T mutation changes committed storage representation",
                "incompressible control is rejected by whole-file cost",
            ],
            "not_proven": [
                "natural video compression",
                "8K streaming",
                "neural inverse graphics",
                "anti-aliasing or photographic material reconstruction",
                "compression near 100 percent on external media",
            ],
        },
    }
    (root / "report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash = _seal_probe(root)
    return {
        "status": report["status"],
        "output": str(root),
        "report": str(root / "report.json"),
        "manifest": str(root / "PROBE_MANIFEST.json"),
        "manifest_sha256": manifest_hash,
        "gates": gates,
        "structured_archive_bytes": structured_default["archive_bytes"],
        "structured_source_bytes": len(structured),
        "structured_reduction_fraction": structured_default[
            "whole_archive_reduction_fraction"
        ],
        "noise_verdict": noise_default["cost_verdict"],
    }


__all__ = [
    "CASVProbeError",
    "make_noise_probe_video",
    "make_structured_probe_video",
    "run_casv_probe",
]
