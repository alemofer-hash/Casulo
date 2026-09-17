"""Verify the self-contained Casulo 6x evidence package.

This command deliberately uses only Python's standard library so a buyer or an
independent reviewer can run it in a clean checkout.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "evidence" / "2026-07-30-marco4-6x"
EVIDENCE_FILE = EVIDENCE_DIR / "evidence.json"
DEMO_FILE = EVIDENCE_DIR / "index.html"
CHECKSUM_FILE = EVIDENCE_DIR / "SHA256SUMS"


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
        if tag == "script" and attributes.get("id") == "frozen-evidence":
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


def _require_equal(label: str, actual: Any, expected: Any) -> None:
    if isinstance(actual, float) or isinstance(expected, float):
        if not math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-12):
            raise AssertionError(f"{label}: {actual!r} != {expected!r}")
        return
    if actual != expected:
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")


def _load_embedded_evidence(html: str) -> dict[str, Any]:
    parser = _EvidenceScriptParser()
    parser.feed(html)
    if not parser.parts:
        raise AssertionError("demonstração não contém frozen-evidence")
    return json.loads("".join(parser.parts))


def verify() -> list[str]:
    evidence = json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
    html = DEMO_FILE.read_text(encoding="utf-8")
    full_path = ROOT / evidence["sources"]["full_report"]
    simd_path = ROOT / evidence["sources"]["simd_report"]
    full = json.loads(full_path.read_text(encoding="utf-8"))
    simd = json.loads(simd_path.read_text(encoding="utf-8"))
    result = evidence["result"]

    checks: list[str] = []

    checksum_entries = {}
    for line in CHECKSUM_FILE.read_text(encoding="ascii").splitlines():
        expected_hash, relative_path = line.split("  ", maxsplit=1)
        checksum_entries[relative_path] = expected_hash
    for relative_path, expected_hash in checksum_entries.items():
        _require_equal(
            f"SHA256SUMS {relative_path}",
            _sha256(ROOT / relative_path),
            expected_hash,
        )
    checks.append("the package checksum manifest matches every listed file")

    _require_equal(
        "hash do relatório completo",
        _sha256(full_path),
        evidence["fingerprints"]["source_full_report_file_sha256"],
    )
    _require_equal(
        "hash do relatório SIMD",
        _sha256(simd_path),
        evidence["fingerprints"]["source_simd_report_file_sha256"],
    )
    checks.append("source reports preserved by SHA-256")

    comparisons = (
        (
            "ganho mediano pareado",
            result["paired_speedup_median"],
            full["comparison"]["paired_wall_speedup_median"],
        ),
        (
            "limite inferior IC95%",
            result["paired_speedup_ci95"]["lower"],
            full["comparison"]["paired_wall_speedup_ci95"]["lower"],
        ),
        (
            "limite superior IC95%",
            result["paired_speedup_ci95"]["upper"],
            full["comparison"]["paired_wall_speedup_ci95"]["upper"],
        ),
        (
            "Python ns/registro",
            result["python_scalar_ns_per_record"],
            full["python_scalar"]["wall_ns_per_record"],
        ),
        (
            "Casulo ns/registro",
            result["casulo_native_ns_per_record"],
            full["c99_native"]["wall_ns_per_record"],
        ),
        (
            "fingerprint do dataset",
            evidence["fingerprints"]["dataset_canonical_sha256"],
            full["dataset_sha256"],
        ),
        (
            "fingerprint da saída",
            evidence["fingerprints"]["equivalent_output_sha256"],
            full["equivalence_sha256"],
        ),
        (
            "identidade do artefato",
            evidence["fingerprints"]["artifact_id"],
            full["artifact_id"],
        ),
        (
            "ganho SIMD pareado",
            evidence["simd"]["paired_speedup_median"],
            simd["comparison"]["paired_wall_speedup_median"],
        ),
    )
    for label, actual, expected in comparisons:
        _require_equal(label, actual, expected)
    checks.append("frozen fields match the scientific reports")

    _require_equal(
        "equivalência do envelope completo",
        result["semantically_equivalent"],
        full["comparison"]["semantically_equivalent"],
    )
    _require_equal(
        "equivalência SIMD",
        result["semantically_equivalent"],
        simd["comparison"]["semantically_equivalent"],
    )
    if result["paired_speedup_ci95"]["lower"] <= 1.0:
        raise AssertionError("intervalo de confiança não demonstra ganho")
    checks.append("equivalence preserved and the full CI95 is above 1x")

    embedded = _load_embedded_evidence(html)
    _require_equal("JSON embutido na demonstração", embedded, evidence)
    checks.append("the demo embeds the exact canonical evidence")

    external_patterns = (
        r"<script[^>]+\bsrc\s*=",
        r"<link[^>]+\bhref\s*=",
        r"\bfetch\s*\(",
        r"\bhttps?://",
        r"url\(\s*['\"]?//",
    )
    for pattern in external_patterns:
        if re.search(pattern, html, flags=re.IGNORECASE):
            raise AssertionError(f"recurso externo detectado por {pattern!r}")
    checks.append("the demo is self-contained, without network or telemetry")

    return checks


def main() -> int:
    try:
        checks = verify()
    except (AssertionError, KeyError, OSError, ValueError) as error:
        print(f"FALHA: {error}", file=sys.stderr)
        return 1

    print("CASULO - FROZEN EVIDENCE IS VALID")
    for check in checks:
        print(f"  [OK] {check}")
    print(f"  [OK] {len(checks)} gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
