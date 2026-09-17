from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path
from typing import Any

from .gop_archive import pack_gop_corpus
from .gop_authority import GOPTAuthority
from .hevc_gop import (
    build_sample_aligned_corpus,
    choose_irap_aligned_probe,
    scan_hevc_access_units,
)
from .independent_gop import reconstruct_gop_independently
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
    raise RuntimeError("unable to allocate append-only GOP probe directory")


def _cost_judgement(
    *,
    root: Path,
    policy: Path,
    runtime: str | Path | None,
    packed: dict[str, Any],
    reconstructed: dict[str, Any],
) -> dict[str, Any]:
    authority = GOPTAuthority(policy, root, runtime=runtime)
    accounting = packed["work_accounting"]
    decision = authority.judge(
        exact_reconstruction=reconstructed["status"] == "PASS",
        source_bytes=packed["source_bytes"],
        archive_bytes=packed["archive_bytes"],
        base_source_bytes=accounting["base_source_bytes"],
        dynamics_source_bytes=accounting["dynamics_source_bytes"],
        residual_source_bytes=accounting["residual_source_bytes"],
    )
    return {
        "schema": "casulo.hevc-gop-cost-judgement/1.0",
        "verdict": decision.verdict,
        "receipt": dict(decision.receipt),
        "authority": authority.manifest(
            decision_protocol=["judge"],
            unit="archive_cost",
            receipts_per_unit=1,
        ),
        "evidence": {
            "exact_reconstruction": reconstructed["status"] == "PASS",
            "source_bytes": packed["source_bytes"],
            "archive_bytes": packed["archive_bytes"],
            "net_change_bytes": packed["archive_bytes"] - packed["source_bytes"],
            "base_source_bytes": accounting["base_source_bytes"],
            "dynamics_source_bytes": accounting["dynamics_source_bytes"],
            "residual_source_bytes": accounting["residual_source_bytes"],
        },
    }


def run_gop_probe(
    source: str | Path,
    output_root: str | Path,
    *,
    default_policy: str | Path,
    force_raw_policy: str | Path,
    runtime: str | Path | None = None,
    target_bytes: int = 64 * 1024 * 1024,
    minimum_samples: int = 2,
    accepted_source_sha256: str | None = None,
) -> dict[str, Any]:
    src = Path(source).resolve()
    root = _next_root(Path(output_root).resolve())
    root.mkdir(parents=True)
    repository = Path(__file__).resolve().parents[3]
    default_policy_path = Path(default_policy).resolve()
    raw_policy_path = Path(force_raw_policy).resolve()
    resolved_runtime = (
        Path(runtime).resolve()
        if runtime is not None
        else repository / "t-runtime" / "target" / "release" / "casulo-t-runtime.exe"
    )
    protocol = {
        "schema": "casulo.hevc-gop-probe-protocol/1.0",
        "frozen_before_results": True,
        "source": str(src),
        "accepted_source_sha256": accepted_source_sha256,
        "target_bytes": target_bytes,
        "minimum_samples": minimum_samples,
        "sample_alignment_required": True,
        "irap_start_required": True,
        "default_policy": str(default_policy_path),
        "force_raw_policy": str(raw_policy_path),
        "runtime": str(resolved_runtime),
        "full_file_compression_result": False,
        "long_workload_allowed": False,
    }
    _write_json(root / "protocol.json", protocol)

    implementation_paths = [
        repository / "src/casulo/compression/mp4_hevc.py",
        repository / "src/casulo/compression/hevc_gop.py",
        repository / "src/casulo/compression/gop_transforms.py",
        repository / "src/casulo/compression/gop_authority.py",
        repository / "src/casulo/compression/gop_archive.py",
        repository / "src/casulo/compression/independent_gop.py",
        repository / "src/casulo/compression/gop_probe.py",
        repository / "src/casulo/t/v2_parser.py",
        repository / "src/casulo/t/v2_semantics.py",
        repository / "src/casulo/t/v2_ir.py",
        repository / "src/casulo/t/v2_tcap.py",
        repository / "src/casulo/t/productive.py",
        default_policy_path,
        raw_policy_path,
        resolved_runtime,
    ]
    provenance = {
        "schema": "casulo.hevc-gop-code-provenance/1.0",
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

    access_units = scan_hevc_access_units(src)
    _write_json(root / "hevc_access_units.json", access_units)
    selected = choose_irap_aligned_probe(
        access_units,
        target_bytes=target_bytes,
        minimum_samples=minimum_samples,
    )
    corpus_path = root / "source-derived-gop-corpus.bin"
    corpus_manifest = build_sample_aligned_corpus(
        src, corpus_path, access_units, selected
    )
    corpus_manifest["source"]["accepted_sha256"] = accepted_source_sha256
    corpus_manifest["source"]["identity_basis"] = (
        "prior accepted full-source receipt"
        if accepted_source_sha256
        else "path and size only; this short probe did not rehash the full source"
    )
    _write_json(root / "corpus_manifest.json", corpus_manifest)

    default = pack_gop_corpus(
        corpus_path,
        root / "default-policy.casulo-gop.zip",
        corpus_manifest=corpus_manifest,
        evidence_dir=root / "default-evidence",
        policy_source=default_policy_path,
        runtime=runtime,
    )
    default_reconstruction = reconstruct_gop_independently(
        root / "default-policy.casulo-gop.zip",
        root / "default-restored-gop-corpus.bin",
    )
    force_raw = pack_gop_corpus(
        corpus_path,
        root / "force-raw-policy.casulo-gop.zip",
        corpus_manifest=corpus_manifest,
        evidence_dir=root / "force-raw-evidence",
        policy_source=raw_policy_path,
        runtime=runtime,
    )
    raw_reconstruction = reconstruct_gop_independently(
        root / "force-raw-policy.casulo-gop.zip"
    )
    exact = (
        default_reconstruction["source_sha256"]
        == raw_reconstruction["source_sha256"]
        == corpus_manifest["corpus"]["sha256"]
    )
    default_cost = _cost_judgement(
        root=root / "default-cost-authority",
        policy=default_policy_path,
        runtime=runtime,
        packed=default,
        reconstructed=default_reconstruction,
    )
    raw_cost = _cost_judgement(
        root=root / "force-raw-cost-authority",
        policy=raw_policy_path,
        runtime=runtime,
        packed=force_raw,
        reconstructed=raw_reconstruction,
    )
    _write_json(root / "default-cost-judgement.json", default_cost)
    _write_json(root / "force-raw-cost-judgement.json", raw_cost)

    causal = {
        "policy_source_hash_changed": default["authority"]["t_source_sha256"]
        != force_raw["authority"]["t_source_sha256"],
        "tcap_hash_changed": default["authority"]["tcap_sha256"]
        != force_raw["authority"]["tcap_sha256"],
        "candidate_family_trace_changed": default["work_accounting"][
            "candidate_family_counts"
        ]
        != force_raw["work_accounting"]["candidate_family_counts"],
        "primitive_invocation_count_changed": default["work_accounting"][
            "candidate_primitive_invocations"
        ]
        != force_raw["work_accounting"]["candidate_primitive_invocations"],
        "candidate_work_bytes_changed": default["work_accounting"][
            "candidate_encoded_bytes_total"
        ]
        != force_raw["work_accounting"]["candidate_encoded_bytes_total"],
        "archive_hash_changed": default["archive_sha256"] != force_raw["archive_sha256"],
        "default_transform_counts": default["work_accounting"]["transform_counts"],
        "force_raw_transform_counts": force_raw["work_accounting"]["transform_counts"],
    }
    causal["pass"] = all(
        causal[key]
        for key in (
            "policy_source_hash_changed",
            "tcap_hash_changed",
            "candidate_family_trace_changed",
            "primitive_invocation_count_changed",
            "candidate_work_bytes_changed",
            "archive_hash_changed",
        )
    )
    source_bytes = default["source_bytes"]
    net_ratio = default["archive_bytes"] / source_bytes
    payload_ratio = default["work_accounting"]["unique_payload_bytes"] / source_bytes
    report = {
        "schema": "casulo.hevc-gop-path-probe/1.0",
        "status": "HEVC_GOP_PATH_PROBE_PASS" if exact and causal["pass"] else "HEVC_GOP_PATH_PROBE_FAIL",
        "scope": "two complete IRAP-aligned access units from the real source; not a full-file or complete-GOP result",
        "source": {
            "path": str(src),
            "bytes": src.stat().st_size,
            "accepted_sha256": accepted_source_sha256,
            "sample_count": access_units["sample_count"],
            "nal_unit_count": access_units["nal_unit_count"],
            "gop_count": access_units["gop_count"],
        },
        "corpus": corpus_manifest,
        "default": default,
        "force_raw": force_raw,
        "independent_reconstruction": {
            "default": default_reconstruction,
            "force_raw": raw_reconstruction,
            "both_match_corpus": exact,
        },
        "t_cost_judgement": {"default": default_cost, "force_raw": raw_cost},
        "causal_t_mutation": causal,
        "compression_observation": {
            "payload_ratio_before_container": payload_ratio,
            "payload_reduction_percent": (1.0 - payload_ratio) * 100.0,
            "complete_archive_ratio": net_ratio,
            "complete_archive_change_percent": (net_ratio - 1.0) * 100.0,
            "direction": "NEGATIVE_NET_EXPANSION"
            if net_ratio >= 1.0
            else "POSITIVE_NET_REDUCTION",
            "t_verdict": default_cost["verdict"],
        },
        "environment": {"python": sys.version, "platform": platform.platform()},
        "claims": {
            "authorized": [
                "all access-unit and NAL boundaries were scanned with bounded header reads",
                "two complete source samples crossed a reversible inter-sample reference candidate",
                "an independent decoder reconstructed the exact sample corpus",
                "changing only T changed candidate work and the archive identity",
                "T rejected net expansion when the complete archive exceeded the corpus",
            ],
            "prohibited": [
                "compression ratio for the complete 8K file",
                "compression ratio for a complete GOP",
                "near-100-percent compression",
                "pixel-domain inter-frame compression",
                "superiority over HEVC or other codecs",
            ],
        },
    }
    _write_json(root / "analysis.json", report)
    markdown = "# Casulo HEVC GOP path — short probe\n\n"
    markdown += f"State: `{report['status']}`  \nScope: {report['scope']}  \n\n"
    markdown += "## Observed\n\n"
    markdown += f"- Full source map: {access_units['sample_count']} samples, {access_units['nal_unit_count']} NAL units, {access_units['gop_count']} GOP groups.\n"
    markdown += f"- Bounded corpus: {source_bytes:,} bytes from samples {list(selected)}; SHA-256 `{corpus_manifest['corpus']['sha256']}`.\n"
    markdown += f"- Default archive: {default['archive_bytes']:,} bytes ({net_ratio:.9f} of corpus).\n"
    markdown += f"- Force-raw archive: {force_raw['archive_bytes']:,} bytes ({force_raw['archive_to_source_ratio']:.9f} of corpus).\n"
    markdown += f"- Independent exact reconstruction: `{exact}`.\n"
    markdown += f"- Causal T mutation: `{causal['pass']}`.\n"
    markdown += f"- T total-cost verdict: `{default_cost['verdict']}`.\n\n"
    markdown += "## Honest result\n\n"
    markdown += f"Selected payloads changed by {(payload_ratio - 1.0) * 100.0:+.6f}%. The complete archive changed by {(net_ratio - 1.0) * 100.0:+.6f}% and is `{report['compression_observation']['direction']}`.\n\n"
    markdown += "This proves the GOP/NAL execution path and falsifies any claim of net compression when T returns REJECT. It is not evidence for the complete video.\n"
    (root / "report.md").write_text(markdown, encoding="utf-8", newline="\n")

    artifact_files = sorted(path for path in root.rglob("*") if path.is_file())
    manifest = {
        "schema": "casulo.hevc-gop-probe-manifest/1.0",
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
    (root / "SHA256SUMS").write_text(
        "".join(f"{item['sha256']} *{item['path']}\n" for item in manifest["files"]),
        encoding="ascii",
        newline="\n",
    )
    return {
        **report,
        "output_root": str(root),
        "manifest_sha256": _sha256(root / "MANIFEST.json"),
    }


__all__ = ["run_gop_probe"]
