from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .casv_ir import CanonicalVideoSpec
from .casv_probe import make_noise_probe_video, make_structured_probe_video
from .casv_program_stream import pack_casv_program_stream_file
from .independent_casv_program_stream import verify_casv_program_stream


class CASVProgramProbeError(RuntimeError):
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
            {
                "schema": "casulo.casv-program-probe-manifest/0.3",
                "entries": entries,
            }
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


def run_casv_program_probe(
    output: str | Path,
    *,
    default_policy: str | Path,
    force_raw_policy: str | Path,
    runtime: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(output).resolve()
    if root.exists():
        raise CASVProgramProbeError(f"probe directory already exists: {root}")
    root.mkdir(parents=True)
    sources = root / "sources"
    archives = root / "archives"
    evidence = root / "evidence"
    restored = root / "restored"
    for directory in (sources, archives, evidence, restored):
        directory.mkdir()

    rgb_spec = CanonicalVideoSpec(96, 54, 12, 24)
    yuv_spec = CanonicalVideoSpec(64, 36, 8, 24, pixel_format="YUV444P10LE")
    noise_spec = CanonicalVideoSpec(96, 54, 4, 24)
    rgb = make_structured_probe_video(rgb_spec)
    yuv = _structured_yuv444p10le(yuv_spec)
    noise = make_noise_probe_video(noise_spec)
    rgb_path = sources / "structured.rgb"
    yuv_path = sources / "structured-yuv444p10le.yuv"
    noise_path = sources / "noise.rgb"
    rgb_path.write_bytes(rgb)
    yuv_path.write_bytes(yuv)
    noise_path.write_bytes(noise)

    cases = {
        "structured_default": pack_casv_program_stream_file(
            rgb_path,
            rgb_spec,
            archives / "structured-default.casv",
            evidence_dir=evidence / "structured-default",
            policy_source=default_policy,
            runtime=runtime,
            frames_per_segment=4,
        ),
        "structured_force_raw": pack_casv_program_stream_file(
            rgb_path,
            rgb_spec,
            archives / "structured-force-raw.casv",
            evidence_dir=evidence / "structured-force-raw",
            policy_source=force_raw_policy,
            runtime=runtime,
            frames_per_segment=4,
        ),
        "native_yuv10": pack_casv_program_stream_file(
            yuv_path,
            yuv_spec,
            archives / "native-yuv10.casv",
            evidence_dir=evidence / "native-yuv10",
            policy_source=default_policy,
            runtime=runtime,
            frames_per_segment=4,
        ),
        "noise_fallback": pack_casv_program_stream_file(
            noise_path,
            noise_spec,
            archives / "noise-fallback.casv",
            evidence_dir=evidence / "noise-fallback",
            policy_source=default_policy,
            runtime=runtime,
            frames_per_segment=4,
        ),
    }
    verifications: dict[str, dict[str, Any]] = {}
    expected = {
        "structured_default": rgb,
        "structured_force_raw": rgb,
        "native_yuv10": yuv,
        "noise_fallback": noise,
    }
    for name, result in cases.items():
        suffix = ".yuv" if name == "native_yuv10" else ".rgb"
        destination = restored / f"{name}{suffix}"
        verification = verify_casv_program_stream(
            result["archive"],
            destination,
        )
        verifications[name] = verification
        if destination.read_bytes() != expected[name]:
            raise CASVProgramProbeError(f"independent reconstruction differs: {name}")

    structured_default = cases["structured_default"]
    structured_force_raw = cases["structured_force_raw"]
    native_yuv10 = cases["native_yuv10"]
    noise_fallback = cases["noise_fallback"]
    gates = {
        "structured_program_selected": (
            structured_default["storage_modes"]["GENERATIVE_EXACT"] == 3
        ),
        "native_yuv10_program_selected": (
            native_yuv10["storage_modes"]["GENERATIVE_EXACT"] == 2
        ),
        "noise_program_rejected_by_cost": (
            noise_fallback["proposals"]["executed"] == 1
            and noise_fallback["proposals"]["selected"] == 0
        ),
        "t_only_mutation_changed_storage": (
            structured_default["storage_modes"]
            != structured_force_raw["storage_modes"]
            and structured_force_raw["storage_modes"]["CANONICAL_RAW"] == 3
        ),
        "tcap_changed_with_policy": (
            structured_default["authority"]["tcap_sha256"]
            != structured_force_raw["authority"]["tcap_sha256"]
        ),
        "all_independent_roundtrips_exact": all(
            verification["status"] == "PASS"
            for verification in verifications.values()
        ),
        "no_foreign_video_bitstream": all(
            result["claims"]["contains_mp4_or_hevc_payload"] is False
            for result in cases.values()
        ),
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    report = {
        "schema": "casulo.casv-program-probe/0.3",
        "status": status,
        "scope": "SYNTHETIC_SHORT_ENGINEERING_REGRESSION",
        "gates": gates,
        "cases": cases,
        "independent_verifications": verifications,
        "claims": {
            "base_dynamics_residual_path_executed": True,
            "t_policy_mutation_is_causal": gates["t_only_mutation_changed_storage"],
            "native_planar_yuv444p10le_renderer_executed": True,
            "natural_video_compression_proven": False,
            "eight_k_compression_proven": False,
            "near_total_compression_proven": False,
        },
    }
    (root / "probe-report.json").write_bytes(_canonical_json(report) + b"\n")
    manifest_hash, sums_hash, entry_count = _seal(root)
    if status != "PASS":
        raise CASVProgramProbeError(f"CASV/0.3 probe failed: {gates}")
    return {
        **report,
        "output": str(root),
        "manifest_sha256": manifest_hash,
        "sha256sums_sha256": sums_hash,
        "manifest_entries": entry_count,
    }


__all__ = ["CASVProgramProbeError", "run_casv_program_probe"]
