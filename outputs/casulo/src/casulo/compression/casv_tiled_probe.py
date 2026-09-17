from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .casv_ir import CanonicalVideoSpec
from .casv_probe import make_noise_probe_video, make_structured_probe_video
from .casv_tile_ir import summarize_layout
from .casv_tiled_stream import pack_casv_tiled_stream_file
from .independent_casv_tiled_stream import unpack_casv_tiled_stream


class CASVTiledProbeError(RuntimeError):
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


def _structured_yuv444p10le(spec: CanonicalVideoSpec) -> bytes:
    """Build a small native planar fixture without depending on another probe."""

    output = bytearray()
    pixels = spec.width * spec.height
    for frame_index in range(spec.frame_count):
        planes = [
            bytearray(value.to_bytes(2, "little") * pixels)
            for value in (128, 512, 512)
        ]
        x = 4 + frame_index
        for plane, value in zip(planes, (800, 300, 700), strict=True):
            row = value.to_bytes(2, "little") * 12
            for offset_y in range(8):
                start = ((6 + offset_y) * spec.width + x) * 2
                plane[start : start + len(row)] = row
        output.extend(b"".join(planes))
    return bytes(output)


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
            {"schema": "casulo.casv-tiled-probe-manifest/0.4", "entries": entries}
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


def run_casv_tiled_probe(
    output: str | Path,
    *,
    default_policy: str | Path,
    force_raw_policy: str | Path,
    runtime: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(output).resolve()
    if root.exists():
        raise CASVTiledProbeError(f"probe directory already exists: {root}")
    root.mkdir(parents=True)
    sources = root / "sources"
    archives = root / "archives"
    evidence = root / "evidence"
    restored = root / "restored"
    for directory in (sources, archives, evidence, restored):
        directory.mkdir()

    rgb_spec = CanonicalVideoSpec(96, 54, 4, 24)
    yuv_spec = CanonicalVideoSpec(64, 36, 2, 24, pixel_format="YUV444P10LE")
    noise_spec = CanonicalVideoSpec(64, 36, 1, 24)
    payloads = {
        "structured_default": make_structured_probe_video(rgb_spec),
        "structured_force_raw": make_structured_probe_video(rgb_spec),
        "native_yuv10": _structured_yuv444p10le(yuv_spec),
        "noise_fallback": make_noise_probe_video(noise_spec),
    }
    specs = {
        "structured_default": rgb_spec,
        "structured_force_raw": rgb_spec,
        "native_yuv10": yuv_spec,
        "noise_fallback": noise_spec,
    }
    policies = {
        "structured_default": default_policy,
        "structured_force_raw": force_raw_policy,
        "native_yuv10": default_policy,
        "noise_fallback": default_policy,
    }
    cases: dict[str, dict[str, Any]] = {}
    verifications: dict[str, dict[str, Any]] = {}
    for name, payload in payloads.items():
        suffix = ".yuv" if name == "native_yuv10" else ".rgb"
        source = sources / f"{name}{suffix}"
        source.write_bytes(payload)
        cases[name] = pack_casv_tiled_stream_file(
            source,
            specs[name],
            archives / f"{name}.casv",
            evidence_dir=evidence / name,
            policy_source=policies[name],
            runtime=runtime,
            tile_width=32,
            strip_height=18,
        )
        destination = restored / f"{name}{suffix}"
        verifications[name] = unpack_casv_tiled_stream(
            archives / f"{name}.casv",
            destination,
        )
        if destination.read_bytes() != payload:
            raise CASVTiledProbeError(f"independent reconstruction differs: {name}")

    normal = cases["structured_default"]
    forced = cases["structured_force_raw"]
    full_8k_layout = summarize_layout(
        CanonicalVideoSpec(8192, 4320, 1, 30, pixel_format="YUV444P10LE"),
        tile_width=512,
        strip_height=128,
    )
    gates = {
        "all_roundtrips_exact": all(item["status"] == "PASS" for item in verifications.values()),
        "t_only_mutation_changes_storage": (
            normal["storage_modes"] != forced["storage_modes"]
            and forced["storage_modes"] == {
                "CANONICAL_RAW": forced["layout"]["tile_count"]
            }
        ),
        "t_policy_hash_changes": (
            normal["authority"]["t_source_sha256"]
            != forced["authority"]["t_source_sha256"]
        ),
        "every_tile_has_t_receipt": all(
            item["authority"]["storage_decision_count"] == item["layout"]["tile_count"]
            for item in cases.values()
        ),
        "batching_preserves_decision_cardinality": all(
            item["authority"]["physical_batch_invocations"] == item["layout"]["record_count"]
            and item["authority"]["physical_batch_invocations"]
            < item["authority"]["storage_decision_count"]
            for item in cases.values()
        ),
        "full_8k_layout_is_bounded": (
            full_8k_layout["canonical_bytes"] == 212_336_640
            and full_8k_layout["maximum_strip_canonical_bytes"] == 2_097_152
            and full_8k_layout["full_frame_allocation_required"] is False
        ),
        "no_foreign_bitstream": all(
            item["claims"]["contains_mp4_or_hevc_payload"] is False
            for item in cases.values()
        ),
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    report = {
        "schema": "casulo.casv-tiled-probe/0.4",
        "status": status,
        "scope": "SYNTHETIC_SHORT_ENGINEERING_REGRESSION",
        "gates": gates,
        "cases": cases,
        "independent_verifications": verifications,
        "full_8k_layout_arithmetic_only": full_8k_layout,
        "claims": {
            "bounded_spatial_tiling_executed_on_small_inputs": True,
            "full_8k_layout_validated_without_allocating_a_frame": True,
            "full_8k_encode_executed": False,
            "t_policy_mutation_is_causal": gates["t_only_mutation_changes_storage"],
            "natural_video_compression_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (root / "probe-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entry_count = _seal(root)
    if status != "PASS":
        raise CASVTiledProbeError(f"CASV/0.4 probe failed: {gates}")
    return {
        **report,
        "output": str(root),
        "manifest_sha256": manifest_hash,
        "sha256sums_sha256": sums_hash,
        "manifest_entries": entry_count,
    }


__all__ = ["CASVTiledProbeError", "run_casv_tiled_probe"]
