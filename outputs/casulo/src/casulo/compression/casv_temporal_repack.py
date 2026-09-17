from __future__ import annotations

import hashlib
import json
import subprocess
import time
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .casv_ir import CanonicalVideoSpec
from .casv_temporal_stream import pack_casv_temporal_stream_file
from .independent_casv_program_stream import (
    inspect_casv_program_stream,
    verify_casv_program_stream,
)
from .independent_casv_temporal_stream import verify_casv_temporal_stream
from .tooling import resolve_tool


class CASVTemporalRepackError(RuntimeError):
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
    manifest_path = root / "CAMPAIGN_MANIFEST.json"
    manifest_path.write_bytes(
        _canonical_json(
            {"schema": "casulo.casv-temporal-repack-manifest/0.6", "entries": entries}
        )
        + b"\n"
    )
    sums_path = root / "CAMPAIGN_SHA256SUMS"
    sums_path.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
        newline="\n",
    )
    return _sha256_file(manifest_path), _sha256_file(sums_path), len(entries)


def _run(command: Sequence[str], *, timeout_seconds: int = 300) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        timeout=timeout_seconds,
    )
    return {
        "command": list(command),
        "returncode": completed.returncode,
        "wall_seconds": time.perf_counter() - started,
        "stdout": completed.stdout.decode("utf-8", errors="replace")[-8192:],
        "stderr": completed.stderr.decode("utf-8", errors="replace")[-8192:],
        "output_truncated_to_last_bytes": 8192,
    }


def _tool_identity(tool: Path) -> dict[str, Any]:
    version = _run((str(tool), "-version"), timeout_seconds=30)
    if version["returncode"] != 0:
        version = _run((str(tool), "--version"), timeout_seconds=30)
    text = version["stdout"] or version["stderr"]
    return {
        "path": str(tool),
        "sha256": _sha256_file(tool),
        "version_first_line": text.splitlines()[0] if text.splitlines() else "UNKNOWN",
        "version_probe_returncode": version["returncode"],
    }


def _validated_baseline(
    *,
    name: str,
    encoded: Path,
    restored: Path,
    canonical_bytes: int,
    canonical_sha256: str,
    encode: dict[str, Any],
    decode: dict[str, Any],
) -> dict[str, Any]:
    restored_exists = restored.is_file()
    restored_bytes = restored.stat().st_size if restored_exists else None
    restored_sha256 = _sha256_file(restored) if restored_exists else None
    encoded_exists = encoded.is_file()
    valid = (
        encode["returncode"] == 0
        and decode["returncode"] == 0
        and encoded_exists
        and restored_bytes == canonical_bytes
        and restored_sha256 == canonical_sha256
    )
    return {
        "name": name,
        "status": "PASS_EXACT" if valid else "INVALID_BASELINE",
        "valid": valid,
        "encoded_path": str(encoded),
        "encoded_bytes": encoded.stat().st_size if encoded_exists else None,
        "encoded_sha256": _sha256_file(encoded) if encoded_exists else None,
        "restored_path": str(restored),
        "restored_bytes": restored_bytes,
        "restored_sha256": restored_sha256,
        "encode": encode,
        "decode": decode,
    }


def _size_classification(
    candidate_bytes: int,
    baseline_bytes: int,
    canonical_bytes: int,
) -> str:
    relative = candidate_bytes / baseline_bytes
    raw_reduction = 1.0 - candidate_bytes / canonical_bytes
    if raw_reduction >= 0.90 and relative <= 0.50:
        return "BREAKTHROUGH_CANDIDATE"
    if relative <= 0.75:
        return "SUBSTANTIAL_ADVANTAGE"
    if relative <= 0.90:
        return "MATERIAL_ADVANTAGE"
    if relative <= 0.95:
        return "SMALL_ADVANTAGE"
    if relative <= 1.05:
        return "COMPETITIVE"
    return "NEGATIVE"


def _run_baselines(
    root: Path,
    canonical: Path,
    spec: CanonicalVideoSpec,
) -> dict[str, Any]:
    baselines = root / "baselines"
    baselines.mkdir()
    canonical_hash = _sha256_file(canonical)

    zlib_path = baselines / "canonical.zlib"
    zlib_path.write_bytes(zlib.compress(canonical.read_bytes(), level=9))
    zlib_restored = baselines / "canonical.zlib.restored"
    try:
        zlib_restored.write_bytes(zlib.decompress(zlib_path.read_bytes()))
        zlib_error = ""
        zlib_returncode = 0
    except zlib.error as exc:
        zlib_error = str(exc)
        zlib_returncode = 1
    zlib_result = _validated_baseline(
        name="zlib-1.3.1-level9",
        encoded=zlib_path,
        restored=zlib_restored,
        canonical_bytes=spec.expected_bytes,
        canonical_sha256=canonical_hash,
        encode={"command": ["python-zlib", "compress", "level=9"], "returncode": 0},
        decode={
            "command": ["python-zlib", "decompress"],
            "returncode": zlib_returncode,
            "stderr": zlib_error,
        },
    )

    zstd = resolve_tool("zstd")
    ffmpeg = resolve_tool("ffmpeg")
    if zstd is None or ffmpeg is None:
        missing = [
            name
            for name, value in (("zstd", zstd), ("ffmpeg", ffmpeg))
            if value is None
        ]
        raise CASVTemporalRepackError(
            "qualified baseline tool is unavailable: " + ", ".join(missing)
        )

    zstd_path = baselines / "canonical.zst"
    zstd_restored = baselines / "canonical.zst.restored"
    zstd_encode = _run(
        (str(zstd), "-19", "-T1", "-f", str(canonical), "-o", str(zstd_path))
    )
    zstd_decode = _run(
        (str(zstd), "-d", "-f", str(zstd_path), "-o", str(zstd_restored))
    )
    zstd_result = _validated_baseline(
        name="zstd-1.5.7-level19-thread1",
        encoded=zstd_path,
        restored=zstd_restored,
        canonical_bytes=spec.expected_bytes,
        canonical_sha256=canonical_hash,
        encode=zstd_encode,
        decode=zstd_decode,
    )

    common_input = (
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pixel_format",
        {"RGB8": "rgb24", "YUV444P10LE": "yuv444p10le"}[spec.pixel_format],
        "-video_size",
        f"{spec.width}x{spec.height}",
        "-framerate",
        f"{spec.fps_numerator}/{spec.fps_denominator}",
        "-i",
        str(canonical),
        "-frames:v",
        str(spec.frame_count),
        "-an",
        "-threads",
        "1",
    )
    decode_prefix = (
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-i",
    )
    pixel_format = {"RGB8": "rgb24", "YUV444P10LE": "yuv444p10le"}[spec.pixel_format]

    ffv1_path = baselines / "canonical.ffv1.mkv"
    ffv1_restored = baselines / "canonical.ffv1.restored"
    ffv1_encode = _run(
        (*common_input, "-c:v", "ffv1", "-level", "3", "-coder", "1", str(ffv1_path))
    )
    ffv1_decode = _run(
        (
            *decode_prefix,
            str(ffv1_path),
            "-map",
            "0:v:0",
            "-frames:v",
            str(spec.frame_count),
            "-f",
            "rawvideo",
            "-pix_fmt",
            pixel_format,
            str(ffv1_restored),
        )
    )
    ffv1_result = _validated_baseline(
        name="ffmpeg-ffv1-level3-thread1",
        encoded=ffv1_path,
        restored=ffv1_restored,
        canonical_bytes=spec.expected_bytes,
        canonical_sha256=canonical_hash,
        encode=ffv1_encode,
        decode=ffv1_decode,
    )

    x265_path = baselines / "canonical.x265-lossless.mkv"
    x265_restored = baselines / "canonical.x265-lossless.restored"
    x265_encode = _run(
        (
            *common_input,
            "-c:v",
            "libx265",
            "-preset",
            "medium",
            "-x265-params",
            "lossless=1:pools=1:frame-threads=1:wpp=0:log-level=error",
            "-pix_fmt",
            pixel_format,
            str(x265_path),
        )
    )
    x265_decode = _run(
        (
            *decode_prefix,
            str(x265_path),
            "-map",
            "0:v:0",
            "-frames:v",
            str(spec.frame_count),
            "-f",
            "rawvideo",
            "-pix_fmt",
            pixel_format,
            str(x265_restored),
        )
    )
    x265_result = _validated_baseline(
        name="ffmpeg-libx265-lossless-medium-thread1",
        encoded=x265_path,
        restored=x265_restored,
        canonical_bytes=spec.expected_bytes,
        canonical_sha256=canonical_hash,
        encode=x265_encode,
        decode=x265_decode,
    )
    results = [zlib_result, zstd_result, ffv1_result, x265_result]
    valid = [item for item in results if item["valid"]]
    return {
        "schema": "casulo.casv-natural-baselines/0.6",
        "tools": {"zstd": _tool_identity(zstd), "ffmpeg": _tool_identity(ffmpeg)},
        "canonical_bytes": spec.expected_bytes,
        "canonical_sha256": canonical_hash,
        "baselines": results,
        "all_baselines_exact": len(valid) == len(results),
        "smallest_valid_baseline": min(
            valid,
            key=lambda item: item["encoded_bytes"],
            default=None,
        ),
    }


def repack_program_to_temporal_campaign(
    source_archive: str | Path,
    output: str | Path,
    *,
    expected_source_archive_sha256: str,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    tile_width: int = 64,
    strip_height: int = 48,
    keyframe_interval: int = 8,
) -> dict[str, Any]:
    """Repack sealed CASV/0.3 media and compare exact natural-video baselines."""

    source_path = Path(source_archive).resolve(strict=True)
    root = Path(output).resolve()
    if root.exists():
        raise CASVTemporalRepackError(f"campaign directory already exists: {root}")
    source_hash = _sha256_file(source_path)
    if source_hash != expected_source_archive_sha256:
        raise CASVTemporalRepackError(
            "CASV/0.3 archive hash differs from the frozen expected hash"
        )
    root.mkdir(parents=True)
    inspected_v03 = inspect_casv_program_stream(source_path)
    media = inspected_v03["manifest"]["canonical_media"]
    spec = CanonicalVideoSpec(
        width=media["width"],
        height=media["height"],
        frame_count=media["frame_count"],
        fps_numerator=media["fps_numerator"],
        fps_denominator=media["fps_denominator"],
        pixel_format=media["pixel_format"],
    )
    frozen_protocol = {
        "schema": "casulo.casv-temporal-natural-protocol/0.6",
        "source_archive": str(source_path),
        "source_archive_bytes": source_path.stat().st_size,
        "source_archive_sha256": source_hash,
        "canonical_media": media,
        "tile_width": tile_width,
        "strip_height": strip_height,
        "keyframe_interval": keyframe_interval,
        "candidate": "CASV/0.6",
        "baselines": [
            "zlib RFC1950 level 9",
            "zstd 1.5.7 level 19 one thread",
            "FFV1 level 3 one thread in Matroska",
            "x265 lossless medium one thread in Matroska",
        ],
        "gate": "every output must reconstruct canonical bytes and SHA-256",
        "frozen_before_candidate_and_baseline_results": True,
    }
    protocol_path = root / "frozen-protocol.json"
    protocol_path.write_bytes(_canonical_json(frozen_protocol) + b"\n")
    protocol_hash = _sha256_file(protocol_path)

    canonical = root / "canonical-source.bin"
    verified_v03 = verify_casv_program_stream(source_path, canonical)
    source_provenance = {
        "schema": "casulo.casv-source-adapter/0.6",
        "kind": "SEALED_CASV_0_3_INDEPENDENT_RECONSTRUCTION",
        "source_archive": str(source_path),
        "source_archive_bytes": source_path.stat().st_size,
        "source_archive_sha256": source_hash,
        "source_archive_format": "CASV/0.3",
        "canonical_bytes": verified_v03["canonical_bytes"],
        "canonical_sha256": verified_v03["canonical_sha256"],
        "ffmpeg_source_decode_executed_during_repack": False,
        "raw_canonical_copy_retained_for_audit": True,
        "frozen_protocol_sha256": protocol_hash,
    }
    archive = root / "real-clip8-temporal.casv"
    packed = pack_casv_temporal_stream_file(
        canonical,
        spec,
        archive,
        evidence_dir=root / "evidence",
        policy_source=policy_source,
        runtime=runtime,
        tile_width=tile_width,
        strip_height=strip_height,
        keyframe_interval=keyframe_interval,
        source_label=canonical.name,
        source_provenance=source_provenance,
    )
    candidate = Path(packed["candidate_path"])
    verified_v06 = verify_casv_temporal_stream(candidate)
    baseline_report = _run_baselines(root, canonical, spec)
    (root / "baseline-report.json").write_bytes(
        _canonical_json(baseline_report) + b"\n"
    )
    smallest = baseline_report["smallest_valid_baseline"]
    candidate_vs_best = (
        smallest["encoded_bytes"] - packed["candidate_archive_bytes"]
        if smallest is not None
        else None
    )
    gates = {
        "source_v03_independent_verification": verified_v03["status"] == "PASS",
        "source_archive_hash_frozen": source_hash == expected_source_archive_sha256,
        "protocol_frozen_before_results": frozen_protocol[
            "frozen_before_candidate_and_baseline_results"
        ],
        "canonical_reconstruction_hash_preserved": (
            verified_v03["canonical_sha256"]
            == packed["canonical_source_sha256"]
            == verified_v06["canonical_sha256"]
        ),
        "temporal_independent_verification": verified_v06["status"] == "PASS",
        "all_mature_baselines_exact": baseline_report["all_baselines_exact"],
        "temporal_candidate_path_executed": packed["temporal_candidate_tiles"] > 0,
        "t_selected_every_tile_and_judged_archive": (
            packed["authority_final"]["receipt_count"]
            == packed["layout"]["tile_count"] + 1
        ),
        "no_foreign_bitstream": (
            packed["claims"]["contains_mp4_or_hevc_payload"] is False
            and verified_v06["foreign_bitstreams_embedded"] is False
        ),
    }
    engineering_status = "PASS" if all(gates.values()) else "FAIL"
    size_classification = (
        _size_classification(
            packed["candidate_archive_bytes"],
            smallest["encoded_bytes"],
            spec.expected_bytes,
        )
        if smallest is not None
        else "INVALID"
    )
    status = (
        f"PASS_ENGINEERING_{size_classification}_VS_MATURE_BASELINE"
        if engineering_status == "PASS"
        else "FAIL_ENGINEERING_GATE"
    )
    report = {
        "schema": "casulo.casv-temporal-real-repack/0.6",
        "status": status,
        "engineering_status": engineering_status,
        "mature_baseline_size_classification": size_classification,
        "proof_scope": "ONE_REAL_NATURAL_256X144_EIGHT_FRAME_CROP",
        "source": source_provenance,
        "frozen_protocol_sha256": protocol_hash,
        "gates": gates,
        "pack": packed,
        "independent_verification": verified_v06,
        "baselines": baseline_report,
        "comparison_to_smallest_valid_baseline": {
            "baseline": smallest["name"] if smallest is not None else None,
            "baseline_bytes": smallest["encoded_bytes"]
            if smallest is not None
            else None,
            "candidate_bytes": packed["candidate_archive_bytes"],
            "advantage_bytes": candidate_vs_best,
            "advantage_fraction": (
                candidate_vs_best / smallest["encoded_bytes"]
                if smallest is not None
                else None
            ),
            "candidate_to_baseline_ratio": (
                packed["candidate_archive_bytes"] / smallest["encoded_bytes"]
                if smallest is not None
                else None
            ),
        },
        "claims": {
            "real_natural_video_crop_executed": True,
            "fresh_source_ffmpeg_decode_executed": False,
            "temporal_candidates_executed": packed["temporal_candidate_tiles"] > 0,
            "temporal_candidates_selected": packed["temporal_selected_tiles"] > 0,
            "exact_canonical_media_preserved": gates[
                "canonical_reconstruction_hash_preserved"
            ],
            "multiple_natural_clip_generalization_proven": False,
            "full_resolution_eight_k_encode_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (root / "repack-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entry_count = _seal(root)
    result = {
        **report,
        "output": str(root),
        "campaign_manifest_sha256": manifest_hash,
        "campaign_sha256sums_sha256": sums_hash,
        "campaign_manifest_entries": entry_count,
    }
    if engineering_status != "PASS":
        raise CASVTemporalRepackError(f"CASV/0.6 real repack gate failed: {gates}")
    return result


__all__ = ["CASVTemporalRepackError", "repack_program_to_temporal_campaign"]
