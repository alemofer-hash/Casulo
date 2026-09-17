from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .casv_compact_stream import pack_casv_compact_stream_file
from .casv_ir import CanonicalVideoSpec
from .independent_casv_compact_stream import verify_casv_compact_stream
from .independent_casv_tiled_stream import (
    inspect_casv_tiled_stream,
    unpack_casv_tiled_stream,
    verify_casv_tiled_stream,
)


class CASVCompactRepackError(RuntimeError):
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
        if path.is_file() and path.name not in {"CAMPAIGN_MANIFEST.json", "CAMPAIGN_SHA256SUMS"}:
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
            {"schema": "casulo.casv-compact-repack-manifest/0.5", "entries": entries}
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


def repack_tiled_to_compact_campaign(
    source_archive: str | Path,
    output: str | Path,
    *,
    expected_source_archive_sha256: str,
    policy_source: str | Path,
    runtime: str | Path | None = None,
    tile_width: int = 64,
    strip_height: int = 48,
) -> dict[str, Any]:
    """Repack sealed CASV/0.4 media into CASV/0.5 without decoding MP4 again."""

    source_path = Path(source_archive).resolve(strict=True)
    root = Path(output).resolve()
    if root.exists():
        raise CASVCompactRepackError(f"campaign directory already exists: {root}")
    source_hash = _sha256_file(source_path)
    if source_hash != expected_source_archive_sha256:
        raise CASVCompactRepackError(
            "CASV/0.4 archive hash differs from the frozen expected hash"
        )
    root.mkdir(parents=True)
    inspected_v04 = inspect_casv_tiled_stream(source_path)
    verified_v04 = verify_casv_tiled_stream(source_path)
    (root / "source-v04-inspection.json").write_bytes(
        _canonical_json(inspected_v04) + b"\n"
    )
    (root / "source-v04-verification.json").write_bytes(
        _canonical_json(verified_v04) + b"\n"
    )

    media = inspected_v04["manifest"]["canonical_media"]
    spec = CanonicalVideoSpec(
        width=media["width"],
        height=media["height"],
        frame_count=media["frame_count"],
        fps_numerator=media["fps_numerator"],
        fps_denominator=media["fps_denominator"],
        pixel_format=media["pixel_format"],
    )
    canonical = root / "canonical-source.bin"
    restored = unpack_casv_tiled_stream(source_path, canonical)
    original_adapter = inspected_v04["manifest"].get("source_adapter", {})
    source_provenance = {
        "schema": "casulo.casv-source-adapter/0.5",
        "kind": "SEALED_CASV_0_4_INDEPENDENT_RECONSTRUCTION",
        "source_archive": str(source_path),
        "source_archive_bytes": source_path.stat().st_size,
        "source_archive_sha256": source_hash,
        "source_archive_format": "CASV/0.4",
        "canonical_bytes": restored["bytes"],
        "canonical_sha256": restored["sha256"],
        "original_source_adapter": original_adapter,
        "ffmpeg_executed_during_repack": False,
        "raw_canonical_copy_retained_for_audit": True,
    }
    archive = root / "real-crop.casv"
    packed = pack_casv_compact_stream_file(
        canonical,
        spec,
        archive,
        evidence_dir=root / "evidence",
        policy_source=policy_source,
        runtime=runtime,
        tile_width=tile_width,
        strip_height=strip_height,
        source_label=canonical.name,
        source_provenance=source_provenance,
    )
    candidate = Path(packed["candidate_path"])
    verified_v05 = verify_casv_compact_stream(candidate)
    gates = {
        "source_v04_independent_verification": verified_v04["status"] == "PASS",
        "source_archive_hash_frozen": source_hash == expected_source_archive_sha256,
        "canonical_reconstruction_hash_preserved": (
            restored["sha256"]
            == verified_v04["canonical_sha256"]
            == packed["canonical_source_sha256"]
            == verified_v05["canonical_sha256"]
        ),
        "compact_independent_verification": verified_v05["status"] == "PASS",
        "compact_archive_published": packed["archive_published"] is True,
        "compact_archive_beats_direct_zlib": (
            packed["cost_verdict"] == "ACCEPT_BEATS_REFERENCE"
            and packed["archive_advantage_bytes_vs_direct_zlib"] > 0
        ),
        "no_foreign_bitstream": (
            packed["claims"]["contains_mp4_or_hevc_payload"] is False
            and verified_v05["foreign_bitstreams_embedded"] is False
        ),
        "no_ffmpeg_redecode": source_provenance["ffmpeg_executed_during_repack"] is False,
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    report = {
        "schema": "casulo.casv-compact-real-repack/0.5",
        "status": status,
        "proof_scope": "REAL_MEDIA_DERIVED_FROM_SEALED_CASV_0_4_ARCHIVE",
        "source": source_provenance,
        "gates": gates,
        "pack": packed,
        "independent_verification": verified_v05,
        "claims": {
            "real_video_derived_pixels_executed": True,
            "fresh_ffmpeg_decode_executed": False,
            "exact_canonical_media_preserved": gates[
                "canonical_reconstruction_hash_preserved"
            ],
            "complete_archive_beats_direct_zlib": gates[
                "compact_archive_beats_direct_zlib"
            ],
            "full_resolution_eight_k_encode_proven": False,
            "natural_video_class_generalization_proven": False,
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
    if status != "PASS":
        raise CASVCompactRepackError(f"CASV/0.5 real repack gate failed: {gates}")
    return result


__all__ = ["CASVCompactRepackError", "repack_tiled_to_compact_campaign"]
