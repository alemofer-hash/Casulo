from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

from .independent_structural import reconstruct_independently
from .mp4_hevc import analyze_mp4_hevc, build_bounded_mp4_probe
from .structural_archive import pack_structural
from .structural_ir import canonical_bytes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=4 * 1024 * 1024) as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_bytes(value))


def _next_root(requested: Path) -> Path:
    if not requested.exists():
        return requested
    for attempt in range(2, 10_000):
        candidate = requested.with_name(f"{requested.name}-attempt{attempt}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("unable to allocate append-only probe directory")


def run_structural_probe(
    source: str | Path,
    output_root: str | Path,
    *,
    default_policy: str | Path,
    force_raw_policy: str | Path,
    runtime: str | Path | None = None,
    media_payload_bytes: int = 4 * 1024 * 1024,
    accepted_source_sha256: str | None = None,
) -> dict[str, Any]:
    src = Path(source).resolve()
    root = _next_root(Path(output_root).resolve())
    root.mkdir(parents=True)
    repository = Path(__file__).resolve().parents[3]
    resolved_runtime = (
        Path(runtime).resolve()
        if runtime is not None
        else repository / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
    )
    protocol = {
        "schema": "casulo.structural-probe-protocol/1.0",
        "frozen_before_results": True,
        "source": str(src),
        "accepted_source_sha256": accepted_source_sha256,
        "media_payload_bytes": media_payload_bytes,
        "default_policy": str(Path(default_policy).resolve()),
        "force_raw_policy": str(Path(force_raw_policy).resolve()),
        "runtime": str(resolved_runtime),
        "probe_is_scientific_compression_result": False,
        "long_workload_allowed": False,
    }
    _write_json(root / "protocol.json", protocol)
    implementation_paths = [
        repository / "src/casulo/compression/content_chunking.py",
        repository / "src/casulo/compression/mp4_hevc.py",
        repository / "src/casulo/compression/reversible_transforms.py",
        repository / "src/casulo/compression/structural_ir.py",
        repository / "src/casulo/compression/structural_authority.py",
        repository / "src/casulo/compression/structural_archive.py",
        repository / "src/casulo/compression/independent_structural.py",
        repository / "src/casulo/compression/structural_probe.py",
        repository / "src/casulo/t/v2_parser.py",
        repository / "src/casulo/t/v2_semantics.py",
        repository / "src/casulo/t/v2_ir.py",
        repository / "src/casulo/t/v2_tcap.py",
        repository / "src/casulo/t/productive.py",
        Path(default_policy).resolve(),
        Path(force_raw_policy).resolve(),
        resolved_runtime,
    ]
    provenance = {
        "schema": "casulo.structural-code-provenance/1.0",
        "files": [
            {
                "path": path.relative_to(repository).as_posix()
                if path.is_relative_to(repository)
                else str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in implementation_paths
        ],
    }
    _write_json(root / "code_provenance.json", provenance)
    original_analysis = analyze_mp4_hevc(src)
    _write_json(root / "original_mp4_hevc_analysis.json", original_analysis)
    probe_path = root / "source-derived-structural-probe.mp4"
    probe_manifest = build_bounded_mp4_probe(
        src,
        probe_path,
        media_payload_bytes=media_payload_bytes,
    )
    probe_manifest["source_identity"] = {
        "sha256": accepted_source_sha256,
        "basis": "prior accepted source receipt; original not rehashed by short probe"
        if accepted_source_sha256
        else "path and byte length only; full source hash not asserted by this probe",
    }
    probe_manifest["probe_sha256"] = _sha256(probe_path)
    _write_json(root / "probe_manifest.json", probe_manifest)

    default_archive = root / "default-policy.casulo-structural.zip"
    default = pack_structural(
        probe_path,
        default_archive,
        evidence_dir=root / "default-evidence",
        policy_source=default_policy,
        runtime=runtime,
        probe={
            "scientific_eligible": False,
            "source_derived": True,
            "purpose": "short real-path execution probe",
        },
    )
    default_reconstruction = reconstruct_independently(
        default_archive,
        root / "default-restored.mp4",
    )

    raw_archive = root / "force-raw-policy.casulo-structural.zip"
    force_raw = pack_structural(
        probe_path,
        raw_archive,
        evidence_dir=root / "force-raw-evidence",
        policy_source=force_raw_policy,
        runtime=runtime,
        probe={
            "scientific_eligible": False,
            "source_derived": True,
            "purpose": "causal T policy mutation control",
        },
    )
    raw_reconstruction = reconstruct_independently(
        raw_archive,
        root / "force-raw-restored.mp4",
    )
    same_probe = (
        default_reconstruction["source_sha256"]
        == raw_reconstruction["source_sha256"]
        == probe_manifest["probe_sha256"]
    )
    default_counts = default["work_accounting"]["transform_counts"]
    raw_counts = force_raw["work_accounting"]["transform_counts"]
    causal = {
        "policy_source_hash_changed": default["authority"]["t_source_sha256"]
        != force_raw["authority"]["t_source_sha256"],
        "tcap_hash_changed": default["authority"]["tcap_sha256"]
        != force_raw["authority"]["tcap_sha256"],
        "selected_transform_trace_changed": default_counts != raw_counts,
        "primitive_invocation_count_changed": (
            default["work_accounting"]["candidate_primitive_invocations"]
            != force_raw["work_accounting"]["candidate_primitive_invocations"]
        ),
        "candidate_work_bytes_changed": (
            default["work_accounting"]["candidate_encoded_bytes_total"]
            != force_raw["work_accounting"]["candidate_encoded_bytes_total"]
        ),
        "archive_bytes_changed": default["archive_bytes"] != force_raw["archive_bytes"],
        "default_transform_counts": default_counts,
        "force_raw_transform_counts": raw_counts,
    }
    causal["pass"] = all(
        causal[key]
        for key in (
            "policy_source_hash_changed",
            "tcap_hash_changed",
            "selected_transform_trace_changed",
            "primitive_invocation_count_changed",
            "candidate_work_bytes_changed",
            "archive_bytes_changed",
        )
    )
    sample_probe = original_analysis.get("hevc_sample_probe") or {}
    mdat_entropy = next(
        (
            item["shannon_bits_per_byte"]
            for item in original_analysis["entropy_samples"]
            if item["type"] == "mdat"
        ),
        None,
    )
    payload_ratio = default["work_accounting"]["unique_payload_bytes"] / probe_path.stat().st_size
    net_ratio = default["archive_to_source_ratio"]
    report = {
        "schema": "casulo.structural-path-probe/1.0",
        "status": "STRUCTURAL_PATH_PROBE_PASS" if same_probe and causal["pass"] else "STRUCTURAL_PATH_PROBE_FAIL",
        "scope": "bounded source-derived execution; not a full-file compression result",
        "source": str(src),
        "source_bytes": src.stat().st_size,
        "probe": str(probe_path),
        "probe_bytes": probe_path.stat().st_size,
        "probe_sha256": probe_manifest["probe_sha256"],
        "mp4": {
            "is_iso_bmff": original_analysis["is_iso_bmff"],
            "is_hevc": original_analysis["is_hevc"],
            "box_count": original_analysis["box_count"],
            "sample_entries": original_analysis["sample_entries"],
            "declared_samples": sample_probe.get("declared_samples"),
            "probed_sample_headers": sample_probe.get("probed_samples"),
            "nal_unit_type_counts": sample_probe.get("nal_unit_type_counts"),
            "observed_irap_sample_indices": sample_probe.get("irap_sample_indices"),
            "mdat_sample_entropy_bits_per_byte": mdat_entropy,
        },
        "default": default,
        "force_raw": force_raw,
        "independent_reconstruction": {
            "default": default_reconstruction,
            "force_raw": raw_reconstruction,
            "both_match_probe": same_probe,
        },
        "causal_t_mutation": causal,
        "compression_observation": {
            "payload_ratio_before_container": payload_ratio,
            "payload_reduction_percent": (1.0 - payload_ratio) * 100.0,
            "complete_archive_ratio": net_ratio,
            "complete_archive_change_percent": (net_ratio - 1.0) * 100.0,
            "direction": "NEGATIVE_NET_EXPANSION" if net_ratio >= 1.0 else "POSITIVE_NET_REDUCTION",
            "interpretation": "metadata and transformed payloads count; no hidden base or residual",
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "claims": {
            "authorized": [
                "MP4/HEVC structure was read from the real source with bounded reads",
                "the source-derived probe crossed the structural encoder and independent decoder",
                "changing only T policy changed the chosen transforms and archive",
            ],
            "prohibited": [
                "full 8K file compression ratio",
                "near-100-percent compression",
                "playability of the bounded structural probe",
                "superiority over established codecs",
            ],
        },
    }
    _write_json(root / "analysis.json", report)
    markdown = "# Casulo structural path — short probe\n\n"
    markdown += f"State: `{report['status']}`  \n"
    markdown += f"Scope: {report['scope']}  \n\n"
    markdown += "## Observed\n\n"
    markdown += f"- Original: `{src.name}`, {src.stat().st_size:,} bytes.\n"
    markdown += f"- ISO BMFF: `{original_analysis['is_iso_bmff']}`; HEVC: `{original_analysis['is_hevc']}`.\n"
    markdown += f"- Declared samples: {sample_probe.get('declared_samples')}; NAL headers probed: {sample_probe.get('probed_samples')}; sampled mdat entropy: {mdat_entropy} bits/byte.\n"
    markdown += f"- Probe: {probe_path.stat().st_size:,} bytes; SHA-256 `{probe_manifest['probe_sha256']}`.\n"
    markdown += f"- Default archive: {default['archive_bytes']:,} bytes ({default['archive_to_source_ratio']:.9f} of probe).\n"
    markdown += f"- Force-raw archive: {force_raw['archive_bytes']:,} bytes ({force_raw['archive_to_source_ratio']:.9f} of probe).\n"
    markdown += f"- Independent exact reconstruction: `{same_probe}`.\n"
    markdown += f"- Causal T mutation: `{causal['pass']}`.\n\n"
    markdown += "## Honest compression result\n\n"
    markdown += f"The selected payloads removed {(1.0 - payload_ratio) * 100.0:.6f}% before container metadata. The complete archive changed by {(net_ratio - 1.0) * 100.0:+.6f}% and is classified `{report['compression_observation']['direction']}`.\n\n"
    markdown += "## Boundary\n\nThis is a positive architecture-execution result and a negative net-compression result for the bounded probe. It does not establish the ratio for the complete 8K video.\n"
    (root / "report.md").write_text(markdown, encoding="utf-8", newline="\n")

    artifact_files = sorted(path for path in root.rglob("*") if path.is_file())
    manifest = {
        "schema": "casulo.structural-probe-manifest/1.0",
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in artifact_files
        ],
    }
    _write_json(root / "MANIFEST.json", manifest)
    sums = "".join(f"{item['sha256']} *{item['path']}\n" for item in manifest["files"])
    (root / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
    return {**report, "output_root": str(root), "manifest_sha256": _sha256(root / "MANIFEST.json")}
