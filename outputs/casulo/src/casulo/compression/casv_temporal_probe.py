from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Mapping

from .casv_ir import CanonicalVideoSpec
from .casv_temporal_stream import pack_casv_temporal_stream_file
from .independent_casv_temporal_stream import (
    inspect_casv_temporal_stream,
    unpack_casv_temporal_stream,
)


class CASVTemporalProbeError(RuntimeError):
    pass


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _temporal_fixture(spec: CanonicalVideoSpec) -> bytes:
    frame_bytes = spec.expected_bytes // spec.frame_count
    base = bytearray(random.Random(20260910).randbytes(frame_bytes))
    frames = []
    for frame in range(spec.frame_count):
        current = bytearray(base)
        for index in range(frame * 31, min(frame * 31 + 97, frame_bytes)):
            current[index] = (current[index] + frame * 7) & 0xFF
        frames.append(bytes(current))
    return b"".join(frames)


def _independent_noise(spec: CanonicalVideoSpec) -> bytes:
    return random.Random(20260911).randbytes(spec.expected_bytes)


def _seal(root: Path) -> tuple[str, str, int]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}:
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    manifest_path = root / "MANIFEST.json"
    manifest_path.write_bytes(
        _canonical_json(
            {"schema": "casulo.casv-temporal-probe-manifest/0.6", "entries": entries}
        )
        + b"\n"
    )
    sums_path = root / "SHA256SUMS"
    sums_path.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
        newline="\n",
    )
    return _sha256_file(manifest_path), _sha256_file(sums_path), len(entries)


def run_casv_temporal_probe(
    output: str | Path,
    *,
    default_policy: str | Path,
    force_spatial_policy: str | Path,
    runtime: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(output).resolve()
    if root.exists():
        raise CASVTemporalProbeError(f"probe directory already exists: {root}")
    root.mkdir(parents=True)
    sources = root / "sources"
    archives = root / "archives"
    evidence = root / "evidence"
    restored = root / "restored"
    for directory in (sources, archives, evidence, restored):
        directory.mkdir()

    temporal_spec = CanonicalVideoSpec(128, 96, 3, 24)
    noise_spec = CanonicalVideoSpec(128, 96, 2, 24)
    temporal = _temporal_fixture(temporal_spec)
    cases_input = {
        "temporal_default": (temporal, temporal_spec, default_policy, 8),
        "temporal_force_spatial": (temporal, temporal_spec, force_spatial_policy, 8),
        "temporal_keyframe_2": (temporal, temporal_spec, default_policy, 2),
        "independent_noise": (
            _independent_noise(noise_spec),
            noise_spec,
            default_policy,
            8,
        ),
    }
    cases: dict[str, dict[str, Any]] = {}
    inspections: dict[str, dict[str, Any]] = {}
    for name, (payload, spec, policy, keyframe_interval) in cases_input.items():
        source = sources / f"{name}.rgb"
        source.write_bytes(payload)
        report = pack_casv_temporal_stream_file(
            source,
            spec,
            archives / f"{name}.casv",
            evidence_dir=evidence / name,
            policy_source=policy,
            runtime=runtime,
            tile_width=64,
            strip_height=48,
            keyframe_interval=keyframe_interval,
        )
        candidate = Path(report["candidate_path"])
        destination = restored / f"{name}.rgb"
        reconstruction = unpack_casv_temporal_stream(candidate, destination)
        if destination.read_bytes() != payload:
            raise CASVTemporalProbeError(
                f"independent temporal reconstruction differs: {name}"
            )
        cases[name] = {**report, "reconstruction": reconstruction}
        inspections[name] = inspect_casv_temporal_stream(candidate)

    normal = cases["temporal_default"]
    forced = cases["temporal_force_spatial"]
    keyframed = inspections["temporal_keyframe_2"]
    noise = cases["independent_noise"]
    frame_two = [
        record for record in keyframed["records"] if record["frame_index"] == 2
    ]
    gates = {
        "all_candidate_roundtrips_exact": all(
            case["reconstruction"]["status"] == "PASS" for case in cases.values()
        ),
        "temporal_candidates_executed": normal["temporal_candidate_tiles"] > 0,
        "temporal_candidates_selected": normal["temporal_selected_tiles"] > 0,
        "temporal_archive_beats_reference": (
            normal["status"] == "PASS_BEATS_DIRECT_ZLIB"
            and normal["archive_advantage_bytes_vs_direct_zlib"] > 0
        ),
        "t_mutation_disables_temporal_storage": (
            forced["temporal_selected_tiles"] == 0
            and normal["authority_final"]["tcap_sha256"]
            != forced["authority_final"]["tcap_sha256"]
            and forced["candidate_archive_bytes"] > normal["candidate_archive_bytes"]
        ),
        "keyframe_forbids_temporal_storage": bool(frame_two)
        and all(
            not mode.startswith("TEMPORAL_")
            for record in frame_two
            for mode in record["tile_modes"]
        ),
        "incompressible_candidate_rejected": (
            noise["status"] == "REJECTED_NO_PUBLICATION"
            and noise["archive_published"] is False
        ),
        "every_tile_and_judgement_have_receipts": all(
            case["authority_final"]["receipt_count"] == case["layout"]["tile_count"] + 1
            for case in cases.values()
        ),
        "no_foreign_bitstream": all(
            case["claims"]["contains_mp4_or_hevc_payload"] is False
            for case in cases.values()
        ),
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    report = {
        "schema": "casulo.casv-temporal-probe/0.6",
        "status": status,
        "scope": "SYNTHETIC_SHORT_ENGINEERING_REGRESSION",
        "gates": gates,
        "cases": cases,
        "claims": {
            "temporal_pipeline_executed": True,
            "t_policy_mutation_is_causal": gates[
                "t_mutation_disables_temporal_storage"
            ],
            "natural_video_compression_proven": False,
            "full_8k_encode_executed": False,
            "near_total_compression_proven": False,
        },
    }
    (root / "probe-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entry_count = _seal(root)
    if status != "PASS":
        raise CASVTemporalProbeError(f"CASV/0.6 probe failed: {gates}")
    return {
        **report,
        "output": str(root),
        "manifest_sha256": manifest_hash,
        "sha256sums_sha256": sums_hash,
        "manifest_entries": entry_count,
    }


__all__ = ["CASVTemporalProbeError", "run_casv_temporal_probe"]
