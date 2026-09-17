from __future__ import annotations

import hashlib
import json
import math
import os
import random
from pathlib import Path
from typing import Any, Mapping

from .casv_ir import CanonicalVideoSpec
from .casv_motion_stream import pack_casv_motion_stream_file
from .casv_temporal_repack import _run_baselines
from .independent_casv_motion_stream import verify_casv_motion_stream
from .independent_casv_program_stream import verify_casv_program_stream


EXPECTED_PREREGISTRATION_SHA256 = (
    "8da4b77d1a35d4aebf65b5ece1b72dfa5c98033f404f201b4503e398e26fa226"
)
MATURE_BASELINE_NAMES = frozenset(
    {
        "zstd-1.5.7-level19-thread1",
        "ffmpeg-ffv1-level3-thread1",
        "ffmpeg-libx265-lossless-medium-thread1",
    }
)


class CASVMotionCampaignError(RuntimeError):
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
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _seal(root: Path) -> tuple[str, str, int]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {
            "CAMPAIGN_MANIFEST.json",
            "CAMPAIGN_SHA256SUMS",
        }:
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    manifest = root / "CAMPAIGN_MANIFEST.json"
    manifest.write_bytes(
        _canonical_json(
            {"schema": "casulo.casv-motion-campaign-manifest/0.7", "entries": entries}
        )
        + b"\n"
    )
    sums = root / "CAMPAIGN_SHA256SUMS"
    sums.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
        newline="\n",
    )
    return _sha256_file(manifest), _sha256_file(sums), len(entries)


def _validate_preregistration(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not path.is_file() or _sha256_file(path) != expected_sha256:
        raise CASVMotionCampaignError("preregistration hash differs before campaign")
    try:
        protocol = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CASVMotionCampaignError("preregistration is not canonical JSON") from exc
    expected_candidate = {
        "format": "CASV/0.7",
        "tile_width": 40,
        "strip_height": 48,
        "keyframe_interval": 8,
        "motion_search_radius_pixels": 8,
        "motion_score_stride_pixels": 4,
        "motion_finalists_per_residual_family": 4,
        "motion_vector_bytes": 2,
        "result_cache": "FORBIDDEN",
    }
    if protocol.get("schema") != "casulo.casv-motion-preregistration/0.7":
        raise CASVMotionCampaignError("preregistration schema differs")
    candidate = protocol.get("candidate", {})
    if any(candidate.get(key) != value for key, value in expected_candidate.items()):
        raise CASVMotionCampaignError("preregistered candidate parameters differ")
    holdouts = protocol.get("holdouts")
    if not isinstance(holdouts, list) or len(holdouts) != 3:
        raise CASVMotionCampaignError("preregistered holdout count differs")
    return protocol


def _crop_planar_video(
    source: Path,
    destination: Path,
    source_spec: CanonicalVideoSpec,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    start_frame: int,
    frames: int,
) -> CanonicalVideoSpec:
    if source_spec.pixel_format != "YUV444P10LE":
        raise CASVMotionCampaignError("natural holdout source is not YUV444P10LE")
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x + width > source_spec.width
        or y + height > source_spec.height
        or start_frame < 0
        or frames <= 0
        or start_frame + frames > source_spec.frame_count
    ):
        raise CASVMotionCampaignError("natural holdout crop exceeds source")
    bytes_per_pixel = 2
    plane_count = 3
    source_row = source_spec.width * bytes_per_pixel
    plane_bytes = source_spec.width * source_spec.height * bytes_per_pixel
    frame_bytes = plane_bytes * plane_count
    row_bytes = width * bytes_per_pixel
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        for frame_index in range(start_frame, start_frame + frames):
            for plane_index in range(plane_count):
                base = (
                    frame_index * frame_bytes
                    + plane_index * plane_bytes
                    + y * source_row
                    + x * bytes_per_pixel
                )
                for row in range(height):
                    input_stream.seek(base + row * source_row)
                    payload = input_stream.read(row_bytes)
                    if len(payload) != row_bytes:
                        raise CASVMotionCampaignError("natural source ended during crop")
                    output_stream.write(payload)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    return CanonicalVideoSpec(
        width=width,
        height=height,
        frame_count=frames,
        fps_numerator=source_spec.fps_numerator,
        fps_denominator=source_spec.fps_denominator,
        pixel_format="YUV444P10LE",
    )


def _shifted_probe(spec: CanonicalVideoSpec) -> bytes:
    randomizer = random.Random(20260911)
    dx = 3
    frame_bytes = spec.width * spec.height * 3
    row_bytes = spec.width * 3
    first = randomizer.randbytes(frame_bytes)
    result = [first]
    previous = first
    for _frame in range(1, spec.frame_count):
        current = bytearray(frame_bytes)
        copied = (spec.width - dx) * 3
        for y in range(spec.height):
            row = y * row_bytes
            current[row : row + copied] = previous[
                row + dx * 3 : row + dx * 3 + copied
            ]
            current[row + copied : row + row_bytes] = randomizer.randbytes(dx * 3)
        previous = bytes(current)
        result.append(previous)
    return b"".join(result)


def _run_causal_probe(
    root: Path,
    *,
    default_policy: Path,
    force_no_motion_policy: Path,
    runtime: str | Path | None,
) -> dict[str, Any]:
    root.mkdir()
    spec = CanonicalVideoSpec(64, 32, 3, 24)
    canonical = root / "shifted-rgb8.bin"
    canonical.write_bytes(_shifted_probe(spec))
    reports: dict[str, dict[str, Any]] = {}
    for label, policy in (
        ("default", default_policy),
        ("force-no-motion", force_no_motion_policy),
    ):
        arm = root / label
        reports[label] = pack_casv_motion_stream_file(
            canonical,
            spec,
            arm / "probe.casv",
            evidence_dir=arm / "evidence",
            policy_source=policy,
            runtime=runtime,
            tile_width=16,
            strip_height=16,
            keyframe_interval=8,
            motion_radius=4,
            score_stride_pixels=2,
            motion_finalists=4,
            source_label=canonical.name,
        )
    default = reports["default"]
    mutation = reports["force-no-motion"]
    gates = {
        "default_selected_motion": default["motion_selected_tiles"] > 0,
        "mutation_selected_no_motion": mutation["motion_selected_tiles"] == 0,
        "tcap_hash_changed": (
            default["authority_final"]["tcap_sha256"]
            != mutation["authority_final"]["tcap_sha256"]
        ),
        "decision_trace_changed": (
            default["authority_final"]["decision_trace_sha256"]
            != mutation["authority_final"]["decision_trace_sha256"]
        ),
        "mutation_increased_archive_bytes": (
            mutation["candidate_archive_bytes"] > default["candidate_archive_bytes"]
        ),
        "both_exact": default["exact_media"] and mutation["exact_media"],
        "canonical_hash_preserved": (
            default["canonical_source_sha256"]
            == mutation["canonical_source_sha256"]
            == _sha256_file(canonical)
        ),
    }
    return {
        "schema": "casulo.casv-motion-causal-probe/0.7",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gates": gates,
        "canonical_bytes": canonical.stat().st_size,
        "canonical_sha256": _sha256_file(canonical),
        "default": default,
        "force_no_motion": mutation,
    }


def run_motion_holdout_campaign(
    preregistration: str | Path,
    output: str | Path,
    *,
    default_policy: str | Path,
    force_no_motion_policy: str | Path,
    runtime: str | Path | None = None,
    expected_preregistration_sha256: str = EXPECTED_PREREGISTRATION_SHA256,
) -> dict[str, Any]:
    prereg_path = Path(preregistration).resolve()
    root = Path(output).resolve()
    protocol = _validate_preregistration(
        prereg_path, expected_preregistration_sha256
    )
    if root.exists():
        raise CASVMotionCampaignError(f"campaign directory already exists: {root}")
    source_record = protocol["source"]
    source_archive = Path(source_record["archive"]).resolve(strict=True)
    if (
        not source_archive.is_file()
        or source_archive.stat().st_size != source_record["archive_bytes"]
        or _sha256_file(source_archive) != source_record["archive_sha256"]
    ):
        raise CASVMotionCampaignError("sealed CASV/0.3 source differs before campaign")
    default_policy_path = Path(default_policy).resolve(strict=True)
    mutation_policy_path = Path(force_no_motion_policy).resolve(strict=True)

    root.mkdir(parents=True)
    (root / "preregistered-protocol.json").write_bytes(prereg_path.read_bytes())
    canonical_source = root / "sealed-source-canonical.bin"
    source_verification = verify_casv_program_stream(
        source_archive, canonical_source
    )
    source_spec = CanonicalVideoSpec(
        width=source_record["width"],
        height=source_record["height"],
        frame_count=source_record["frames"],
        fps_numerator=source_record["fps_numerator"],
        fps_denominator=source_record["fps_denominator"],
        pixel_format=source_record["pixel_format"],
    )
    source_gate = (
        source_verification["status"] == "PASS"
        and source_verification["canonical_bytes"] == source_record["canonical_bytes"]
        and source_verification["canonical_sha256"]
        == source_record["canonical_sha256"]
        == _sha256_file(canonical_source)
    )
    if not source_gate:
        raise CASVMotionCampaignError("sealed source reconstruction differs")

    causal_probe = _run_causal_probe(
        root / "causal-probe",
        default_policy=default_policy_path,
        force_no_motion_policy=mutation_policy_path,
        runtime=runtime,
    )
    (root / "causal-probe.json").write_bytes(_canonical_json(causal_probe) + b"\n")

    holdout_results: list[dict[str, Any]] = []
    for holdout in protocol["holdouts"]:
        case_id = holdout["case_id"]
        case_root = root / "holdouts" / case_id
        case_root.mkdir(parents=True)
        canonical = case_root / "canonical.yuv444p10le"
        spec = _crop_planar_video(
            canonical_source,
            canonical,
            source_spec,
            x=holdout["x"],
            y=holdout["y"],
            width=holdout["width"],
            height=holdout["height"],
            start_frame=holdout["start_frame"],
            frames=holdout["frames"],
        )
        candidate_report = pack_casv_motion_stream_file(
            canonical,
            spec,
            case_root / f"{case_id}.casv",
            evidence_dir=case_root / "evidence",
            policy_source=default_policy_path,
            runtime=runtime,
            tile_width=protocol["candidate"]["tile_width"],
            strip_height=protocol["candidate"]["strip_height"],
            keyframe_interval=protocol["candidate"]["keyframe_interval"],
            motion_radius=protocol["candidate"]["motion_search_radius_pixels"],
            score_stride_pixels=protocol["candidate"][
                "motion_score_stride_pixels"
            ],
            motion_finalists=protocol["candidate"][
                "motion_finalists_per_residual_family"
            ],
            source_label=canonical.name,
            source_provenance={
                "kind": "PREREGISTERED_DISJOINT_NATURAL_CROP",
                "sealed_source_archive_sha256": source_record["archive_sha256"],
                "preregistration_sha256": expected_preregistration_sha256,
                "holdout": dict(holdout),
            },
        )
        candidate = Path(candidate_report["candidate_path"])
        verification = verify_casv_motion_stream(candidate)
        baselines = _run_baselines(case_root, canonical, spec)
        mature = [
            item
            for item in baselines["baselines"]
            if item["name"] in MATURE_BASELINE_NAMES and item["valid"]
        ]
        reference = min(mature, key=lambda item: item["encoded_bytes"], default=None)
        ratio = (
            candidate_report["candidate_archive_bytes"] / reference["encoded_bytes"]
            if reference is not None
            else None
        )
        gates = {
            "canonical_crop_exact": (
                canonical.stat().st_size == spec.expected_bytes
                and verification["canonical_sha256"] == _sha256_file(canonical)
            ),
            "candidate_exact": verification["status"] == "PASS",
            "all_baselines_exact": baselines["all_baselines_exact"],
            "all_three_mature_references_exact": len(mature) == 3,
            "t_selected_every_tile_and_judged": (
                candidate_report["authority_final"]["receipt_count"]
                == candidate_report["layout"]["tile_count"] + 1
            ),
            "motion_path_executed": candidate_report["motion_candidate_tiles"] > 0,
            "no_foreign_bitstream": (
                verification["foreign_bitstreams_embedded"] is False
                and candidate_report["claims"]["contains_mp4_or_hevc_payload"]
                is False
            ),
        }
        holdout_results.append(
            {
                "case_id": case_id,
                "crop": dict(holdout),
                "canonical_bytes": canonical.stat().st_size,
                "canonical_sha256": _sha256_file(canonical),
                "candidate": candidate_report,
                "independent_verification": verification,
                "baselines": baselines,
                "reference": reference,
                "candidate_to_reference_ratio": ratio,
                "material_win": ratio is not None and ratio <= 0.90,
                "within_maximum_regression": ratio is not None and ratio <= 1.05,
                "engineering_gates": gates,
                "engineering_status": "PASS" if all(gates.values()) else "FAIL",
            }
        )
        (case_root / "case-report.json").write_bytes(
            _canonical_json(holdout_results[-1]) + b"\n"
        )

    ratios = [item["candidate_to_reference_ratio"] for item in holdout_results]
    valid_ratios = [float(value) for value in ratios if value is not None]
    geometric_mean = (
        math.exp(sum(math.log(value) for value in valid_ratios) / len(valid_ratios))
        if len(valid_ratios) == len(holdout_results)
        else None
    )
    gate = protocol["competitive_gate"]
    material_wins = sum(item["material_win"] for item in holdout_results)
    competitive_gates = {
        "required_material_wins": material_wins
        >= gate["required_material_wins"],
        "geometric_mean_ratio": geometric_mean is not None
        and geometric_mean <= gate["required_geometric_mean_ratio_max"],
        "maximum_single_holdout_ratio": bool(valid_ratios)
        and max(valid_ratios) <= gate["maximum_allowed_single_holdout_ratio"],
    }
    engineering_gates = {
        "preregistration_hash_preserved": (
            _sha256_file(root / "preregistered-protocol.json")
            == expected_preregistration_sha256
        ),
        "sealed_source_exact": source_gate,
        "causal_t_mutation": causal_probe["status"] == "PASS",
        "three_disjoint_holdouts": len(holdout_results) == 3,
        "all_holdout_engineering_gates": all(
            item["engineering_status"] == "PASS" for item in holdout_results
        ),
    }
    engineering_status = "PASS" if all(engineering_gates.values()) else "FAIL"
    competitive_status = "PASS" if all(competitive_gates.values()) else "FAIL"
    final_status = (
        "PASS_MOTION_BRANCH_MATERIAL_ADVANTAGE"
        if engineering_status == "PASS" and competitive_status == "PASS"
        else gate["failure_action"]
        if engineering_status == "PASS"
        else "FAIL_ENGINEERING_GATE"
    )
    report = {
        "schema": "casulo.casv-motion-natural-holdouts/0.7",
        "status": final_status,
        "engineering_status": engineering_status,
        "competitive_status": competitive_status,
        "proof_scope": "THREE_PREREGISTERED_NATURAL_80X144_EIGHT_FRAME_HOLDOUTS",
        "preregistration": {
            "path": str(prereg_path),
            "sha256": expected_preregistration_sha256,
            "frozen_before_algorithm_implementation": True,
        },
        "source_verification": source_verification,
        "causal_probe": causal_probe,
        "holdouts": holdout_results,
        "ratios": valid_ratios,
        "material_wins": material_wins,
        "geometric_mean_ratio": geometric_mean,
        "maximum_ratio": max(valid_ratios) if valid_ratios else None,
        "competitive_gate": gate,
        "competitive_gates": competitive_gates,
        "engineering_gates": engineering_gates,
        "claims": {
            "bounded_integer_motion_path_implemented": True,
            "t_only_causal_mutation_proven": causal_probe["status"] == "PASS",
            "three_natural_holdouts_executed": len(holdout_results) == 3,
            "general_video_codec_advantage": False,
            "full_resolution_eight_k_encode": False,
            "audio": False,
            "near_total_compression": False,
        },
    }
    (root / "campaign-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entries = _seal(root)
    result = {
        **report,
        "output": str(root),
        "campaign_manifest_sha256": manifest_hash,
        "campaign_sha256sums_sha256": sums_hash,
        "campaign_manifest_entries": entries,
    }
    if engineering_status != "PASS":
        raise CASVMotionCampaignError(
            f"CASV/0.7 engineering campaign gate failed: {engineering_gates}"
        )
    return result


__all__ = [
    "CASVMotionCampaignError",
    "EXPECTED_PREREGISTRATION_SHA256",
    "run_motion_holdout_campaign",
]
