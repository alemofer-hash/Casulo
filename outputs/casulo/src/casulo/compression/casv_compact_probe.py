from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .casv_compact_stream import pack_casv_compact_stream_file
from .casv_ir import CanonicalVideoSpec
from .casv_probe import make_noise_probe_video
from .independent_casv_compact_stream import unpack_casv_compact_stream


class CASVCompactProbeError(RuntimeError):
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


def _spatial_ramp_rgb(spec: CanonicalVideoSpec) -> bytes:
    """Exercise spatial prediction without pretending to model natural video."""

    return bytes(
        (
            (x * 17 + y * 29 + frame * 43) & 0xFF
            if channel == 0
            else (x * 13 + y * 7 + frame * 31) & 0xFF
            if channel == 1
            else (x * 3 + y * 19 + frame * 71) & 0xFF
        )
        for frame in range(spec.frame_count)
        for y in range(spec.height)
        for x in range(spec.width)
        for channel in range(3)
    )


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
            {"schema": "casulo.casv-compact-probe-manifest/0.5", "entries": entries}
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


def run_casv_compact_probe(
    output: str | Path,
    *,
    default_policy: str | Path,
    force_raw_policy: str | Path,
    runtime: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(output).resolve()
    if root.exists():
        raise CASVCompactProbeError(f"probe directory already exists: {root}")
    root.mkdir(parents=True)
    sources = root / "sources"
    archives = root / "archives"
    evidence = root / "evidence"
    restored = root / "restored"
    for directory in (sources, archives, evidence, restored):
        directory.mkdir()

    rgb_spec = CanonicalVideoSpec(256, 144, 2, 24)
    yuv_spec = CanonicalVideoSpec(64, 36, 2, 24, pixel_format="YUV444P10LE")
    noise_spec = CanonicalVideoSpec(64, 36, 1, 24)
    cases_input = {
        "spatial_ramp_default": (_spatial_ramp_rgb(rgb_spec), rgb_spec),
        "spatial_ramp_force_raw": (_spatial_ramp_rgb(rgb_spec), rgb_spec),
        "native_yuv10": (_structured_yuv444p10le(yuv_spec), yuv_spec),
        "noise": (make_noise_probe_video(noise_spec), noise_spec),
    }
    cases: dict[str, dict[str, Any]] = {}
    reconstructed: dict[str, dict[str, Any]] = {}
    for name, (payload, spec) in cases_input.items():
        suffix = ".yuv" if spec.pixel_format == "YUV444P10LE" else ".rgb"
        source = sources / f"{name}{suffix}"
        source.write_bytes(payload)
        report = pack_casv_compact_stream_file(
            source,
            spec,
            archives / f"{name}.casv",
            evidence_dir=evidence / name,
            policy_source=(
                force_raw_policy if name == "spatial_ramp_force_raw" else default_policy
            ),
            runtime=runtime,
            tile_width=32,
            strip_height=18,
        )
        cases[name] = report
        candidate = Path(report["candidate_path"])
        destination = restored / f"{name}{suffix}"
        reconstructed[name] = unpack_casv_compact_stream(candidate, destination)
        if destination.read_bytes() != payload:
            raise CASVCompactProbeError(f"independent reconstruction differs: {name}")

    normal = cases["spatial_ramp_default"]
    forced = cases["spatial_ramp_force_raw"]
    noise = cases["noise"]
    gates = {
        "all_candidate_roundtrips_exact": all(
            item["status"] == "PASS" for item in reconstructed.values()
        ),
        "structured_archive_beats_reference": (
            normal["status"] == "PASS_BEATS_DIRECT_ZLIB"
            and normal["archive_advantage_bytes_vs_direct_zlib"] > 0
        ),
        "t_policy_mutation_prevents_publication": (
            forced["archive_published"] is False
            and forced["storage_modes"]
            == {"CANONICAL_RAW": forced["layout"]["tile_count"]}
            and normal["authority_final"]["tcap_sha256"]
            != forced["authority_final"]["tcap_sha256"]
        ),
        "incompressible_candidate_rejected": (
            noise["status"] == "REJECTED_NO_PUBLICATION"
            and noise["archive_published"] is False
        ),
        "every_tile_and_judgement_have_receipts": all(
            item["authority_final"]["receipt_count"]
            == item["layout"]["tile_count"] + 1
            for item in cases.values()
        ),
        "compact_accounting_exact": all(
            item["candidate_archive_bytes"]
            == item["selected_record_stream_bytes"] + item["fixed_container_bytes"]
            for item in cases.values()
        ),
        "no_foreign_bitstream": all(
            item["claims"]["contains_mp4_or_hevc_payload"] is False
            for item in cases.values()
        ),
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    report = {
        "schema": "casulo.casv-compact-probe/0.5",
        "status": status,
        "scope": "SYNTHETIC_SHORT_ENGINEERING_REGRESSION",
        "gates": gates,
        "cases": cases,
        "independent_reconstructions": reconstructed,
        "claims": {
            "compact_container_executed": True,
            "full_archive_reference_gate_executed": True,
            "t_policy_mutation_is_causal": gates[
                "t_policy_mutation_prevents_publication"
            ],
            "natural_video_compression_proven": False,
            "full_8k_encode_executed": False,
            "near_total_compression_proven": False,
        },
    }
    (root / "probe-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entry_count = _seal(root)
    if status != "PASS":
        raise CASVCompactProbeError(f"CASV/0.5 probe failed: {gates}")
    return {
        **report,
        "output": str(root),
        "manifest_sha256": manifest_hash,
        "sha256sums_sha256": sums_hash,
        "manifest_entries": entry_count,
    }


__all__ = ["CASVCompactProbeError", "run_casv_compact_probe"]
