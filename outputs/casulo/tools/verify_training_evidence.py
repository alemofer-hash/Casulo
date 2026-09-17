"""Verify a Casulo/T training evidence bundle with the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = (
    ROOT
    / "benchmarks"
    / "results"
    / "2026-07-30-sprint012-training-proof"
)
EXPECTED_FILES = {
    "SUMMARY.md",
    "artifact/casulo_training.c",
    "artifact/manifest.json",
    "artifact/source.t",
    "dataset.json",
    "training-report.html",
    "training-report.json",
}


class _EvidenceScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capturing = False
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "script" and attributes.get("id") == "training-evidence":
            self._capturing = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capturing:
            self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self.parts.append(data)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_equal(label: str, actual: Any, expected: Any) -> None:
    if isinstance(actual, float) or isinstance(expected, float):
        if not math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-12):
            raise AssertionError(f"{label}: {actual!r} != {expected!r}")
        return
    if actual != expected:
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")


def _flatten(values: Iterable[Any]) -> Iterable[float]:
    for value in values:
        if isinstance(value, list):
            yield from _flatten(value)
        else:
            yield float(value)


def _load_embedded_report(html: str) -> dict[str, Any]:
    parser = _EvidenceScriptParser()
    parser.feed(html)
    if not parser.parts:
        raise AssertionError("training-report.html has no training-evidence payload")
    return json.loads("".join(parser.parts))


def _load_checksums(directory: Path) -> dict[str, str]:
    checksum_file = directory / "SHA256SUMS"
    entries: dict[str, str] = {}
    for line in checksum_file.read_text(encoding="ascii").splitlines():
        expected_hash, relative_path = line.split("  ", maxsplit=1)
        normalized = relative_path.replace("\\", "/")
        candidate = Path(normalized)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise AssertionError(f"unsafe checksum path: {relative_path}")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise AssertionError(f"invalid SHA-256 for {relative_path}")
        entries[normalized] = expected_hash
    _require_equal("checksum file set", set(entries), EXPECTED_FILES)
    return entries


def _verify_dataset(dataset: dict[str, Any], report: dict[str, Any]) -> None:
    manifest = dataset["manifest"]
    _require_equal("dataset protocol", dataset["protocol"], manifest["protocol"])
    _require_equal("dataset manifest in report", report["dataset"], manifest)

    records = int(manifest["records"])
    validation_records = int(manifest["validation_records"])
    features = int(manifest["features"])
    _require_equal("training row count", len(dataset["inputs"]), records)
    _require_equal("training target count", len(dataset["targets"]), records)
    _require_equal(
        "validation row count",
        len(dataset["validation_inputs"]),
        validation_records,
    )
    _require_equal(
        "validation target count",
        len(dataset["validation_targets"]),
        validation_records,
    )
    for label, rows in (
        ("training", dataset["inputs"]),
        ("validation", dataset["validation_inputs"]),
    ):
        if any(len(row) != features for row in rows):
            raise AssertionError(f"{label} dataset has an invalid feature count")

    digest = hashlib.sha256()
    digest.update(dataset["protocol"].encode("ascii"))
    digest.update(str(manifest["seed"]).encode("ascii"))
    for key in (
        "inputs",
        "targets",
        "validation_inputs",
        "validation_targets",
    ):
        for value in _flatten(dataset[key]):
            digest.update(struct.pack("<d", value))
    _require_equal("dataset content SHA-256", digest.hexdigest(), manifest["sha256"])


def _verify_artifact(directory: Path, report: dict[str, Any]) -> None:
    artifact_dir = directory / "artifact"
    manifest = json.loads(
        (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    )
    source = (artifact_dir / manifest["source"]["file"]).read_text(encoding="utf-8")
    native_source = artifact_dir / manifest["native_source"]["file"]

    _require_equal(
        "T source SHA-256",
        _sha256_bytes(source.encode("utf-8")),
        manifest["source"]["sha256"],
    )
    _require_equal(
        "native source SHA-256",
        _sha256(native_source),
        manifest["native_source"]["sha256"],
    )
    canonical = json.dumps(
        {
            "protocol": manifest["protocol"],
            "spec": manifest["spec"],
            "source_sha256": manifest["source"]["sha256"],
            "backend": manifest["backend"],
            "abi": manifest["abi"],
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    artifact_id = "sha256:" + _sha256_bytes(canonical.encode("utf-8"))
    _require_equal("content-addressed artifact", artifact_id, manifest["artifact_id"])
    _require_equal("artifact in report", report["artifact_id"], artifact_id)
    _require_equal("model in report", report["model"], manifest["spec"])


def _independent_bootstrap_lower(
    values: list[float],
    *,
    seed: int,
    resamples: int = 10_000,
) -> float:
    generator = random.Random(seed)
    size = len(values)
    medians = [
        statistics.median(generator.choices(values, k=size))
        for _ in range(resamples)
    ]
    medians.sort()
    return medians[math.floor(0.025 * (resamples - 1))]


def _verify_measurement(report: dict[str, Any]) -> float:
    comparison = report["comparison"]
    quality = report["quality"]
    pytorch_samples = report["pytorch"]["wall_ns_samples"]
    casulo_samples = report["casulo_t"]["wall_ns_samples"]
    speedups = comparison["paired_speedup_samples"]

    _require_equal("benchmark protocol", report["protocol"], "casulo-training-benchmark/0.1")
    _require_equal("number of paired samples", len(pytorch_samples), 21)
    _require_equal("paired sample cardinality", len(casulo_samples), len(pytorch_samples))
    _require_equal("speedup sample cardinality", len(speedups), len(pytorch_samples))
    calculated = [
        float(baseline) / float(candidate)
        for baseline, candidate in zip(pytorch_samples, casulo_samples, strict=True)
    ]
    for index, (actual, expected) in enumerate(zip(speedups, calculated, strict=True)):
        _require_equal(f"paired speedup {index}", actual, expected)
    _require_equal(
        "paired speedup median",
        comparison["paired_speedup_median"],
        statistics.median(calculated),
    )
    _require_equal(
        "ratio of medians",
        comparison["ratio_of_medians"],
        statistics.median(pytorch_samples) / statistics.median(casulo_samples),
    )

    required_equivalence = (
        "same_dataset",
        "same_architecture",
        "same_initial_parameters",
        "same_optimizer",
        "same_learning_rate",
        "same_epochs",
        "pytorch_deterministic",
        "casulo_t_deterministic",
        "equivalent_training",
        "quality_target_reached",
    )
    failed = [field for field in required_equivalence if quality.get(field) is not True]
    if failed:
        raise AssertionError(f"failed quality gates: {', '.join(failed)}")
    if quality["prediction_rmse_difference"] > quality["numeric_tolerance"]:
        raise AssertionError("prediction difference exceeds the numeric tolerance")

    lower = float(comparison["paired_speedup_ci95"]["lower"])
    expected_gate = bool(quality["equivalent_training"]) and bool(
        quality["quality_target_reached"]
    ) and lower >= 6.0
    _require_equal("6x claim gate", comparison["claim_gate_6x"], expected_gate)
    if not expected_gate:
        raise AssertionError("the evidence does not pass the conservative 6x gate")
    independent_lower = _independent_bootstrap_lower(
        calculated,
        seed=int(comparison["paired_speedup_ci95"]["seed"]) ^ 0xCA510,
    )
    if independent_lower < 6.0:
        raise AssertionError(
            f"independent bootstrap lower bound is only {independent_lower:.6f}x"
        )

    scheduler = comparison.get("scheduler")
    if scheduler is not None:
        _require_equal("scheduler request", scheduler["requested_workers"], "auto")
        _require_equal("scheduler selected workers", scheduler["selected_workers"], 1)
    _require_equal("executed workers", comparison["workers"], 1)
    _require_equal("PyTorch baseline", report["baseline"]["name"], "PyTorch eager CPU")
    if report["baseline"]["mkl"] is not True or report["baseline"]["avx2"] is not True:
        raise AssertionError("declared baseline is missing MKL or AVX2")
    if report["energy"]["electrical_energy_measured"] is not False:
        raise AssertionError("this experiment must not claim measured electrical energy")
    return independent_lower


def _load_bundle(directory: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    report = json.loads(
        (directory / "training-report.json").read_text(encoding="utf-8")
    )
    dataset = json.loads((directory / "dataset.json").read_text(encoding="utf-8"))
    html = (directory / "training-report.html").read_text(encoding="utf-8")
    return report, dataset, html


def _verify_visual_report(html: str, report: dict[str, Any]) -> None:
    embedded = _load_embedded_report(html)
    _require_equal("embedded visual report", embedded, report)
    external_patterns = (
        r"<script[^>]+\bsrc\s*=",
        r"<link[^>]+\bhref\s*=",
        r"\bfetch\s*\(",
        r"\bhttps?://",
        r"url\(\s*['\"]?//",
    )
    for pattern in external_patterns:
        if re.search(pattern, html, flags=re.IGNORECASE):
            raise AssertionError(f"external resource detected by {pattern!r}")


def verify(directory: Path = DEFAULT_EVIDENCE_DIR) -> list[str]:
    directory = directory.expanduser().resolve()
    report, dataset, html = _load_bundle(directory)
    checks: list[str] = []

    for relative_path, expected_hash in _load_checksums(directory).items():
        _require_equal(
            f"SHA256SUMS {relative_path}",
            _sha256(directory / relative_path),
            expected_hash,
        )
    checks.append("all seven evidence files match SHA256SUMS")

    _verify_artifact(directory, report)
    checks.append("the generated artifact is content-addressed and intact")

    _verify_dataset(dataset, report)
    checks.append("the serialized dataset matches its canonical SHA-256")

    principal_lower = _verify_measurement(report)
    checks.append(
        "21 paired measurements pass equivalence and an independent bootstrap 6x gate"
    )

    _verify_visual_report(html, report)
    checks.append("the visual report embeds the exact scientific report")

    replication_directories = (
        directory.parent / "2026-07-30-sprint012-training-optimized" / "workers-1",
        directory.parent / "2026-07-30-sprint012-training-auto",
    )
    independent_lowers = [principal_lower]
    for replication_directory in replication_directories:
        replication, replication_dataset, replication_html = _load_bundle(
            replication_directory
        )
        _verify_artifact(replication_directory, replication)
        _verify_dataset(replication_dataset, replication)
        _verify_visual_report(replication_html, replication)
        _require_equal(
            "replication artifact",
            replication["artifact_id"],
            report["artifact_id"],
        )
        _require_equal(
            "replication dataset",
            replication["dataset"]["sha256"],
            report["dataset"]["sha256"],
        )
        independent_lowers.append(_verify_measurement(replication))
    if min(independent_lowers) < 6.0:
        raise AssertionError("one official replication failed the independent 6x gate")
    checks.append(
        "three official 21-pair runs independently keep the bootstrap lower bound above 6x"
    )

    checks.append("all visual reports are self-contained and have no telemetry")

    return checks


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a Casulo/T training evidence bundle."
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
        help="evidence directory (defaults to the official Sprint 012 proof)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    try:
        checks = verify(arguments.directory)
    except (AssertionError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1

    print("CASULO/T TRAINING EVIDENCE IS VALID")
    for check in checks:
        print(f"  [OK] {check}")
    print(f"  [OK] {len(checks)} independent gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
