from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import MANIFEST_SCHEMA, sha256_file, write_json


def render_report(analysis: dict[str, Any], capabilities: dict[str, Any]) -> str:
    terminal = analysis.get("terminal_state", "BLOCKED_PHYSICAL_INSTRUMENT")
    domain = analysis.get("energy_domain")
    lines = [
        f"# Casulo Energy V1 — `{analysis.get('campaign_id')}`",
        "",
        f"**Estado científico:** `{terminal}`",
        "",
        f"- Domínio: `{domain}`",
        f"- Pares válidos: `{analysis.get('valid_pairs', 0)}/{analysis.get('expected_pairs', 0)}`",
        f"- Mediana J_candidato/J_baseline: `{analysis.get('median_ratio_candidate_over_baseline')}`",
        f"- IC bootstrap pareado 95%: `{analysis.get('paired_bootstrap_ci95')}`",
        f"- Direção consistente entre sessões: `{analysis.get('direction_consistent_across_sessions')}`",
        f"- Melhoria material >=10%: `{analysis.get('material_improvement_at_least_10_percent')}`",
        "",
        "RAPL, quando usado, autoriza somente a expressão **energia do pacote CPU**. "
        "Somente um wattímetro físico com bateria controlada autoriza **energia total da máquina**.",
        "",
        "Tempo, temperatura, frequência, utilização e operações lógicas não foram convertidos em joules.",
        "",
        "## Capacidades físicas",
        "",
        f"- CPU_PACKAGE_RAPL: `{capabilities.get('sources', {}).get('CPU_PACKAGE_RAPL')}`",
        f"- TOTAL_SYSTEM_WALL: `{capabilities.get('sources', {}).get('TOTAL_SYSTEM_WALL')}`",
        f"- BATTERY_DELTA: `{capabilities.get('sources', {}).get('BATTERY_DELTA')}`",
        "- LOGICAL_TELEMETRY: `not_energy`",
        "",
        "Nenhuma alegação contra Inductor e nenhuma atribuição do resultado histórico de 8.957846× ao Casulo SO é feita.",
        "",
    ]
    return "\n".join(lines)


def seal_campaign(directory: Path) -> dict[str, Any]:
    root = Path(directory)
    excluded = {"MANIFEST.json", "SHA256SUMS"}
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name not in excluded
    )
    entries = [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in files
    ]
    sums = "".join(f"{item['sha256']}  {item['path']}\n" for item in entries)
    (root / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "campaign_id": root.name,
        "artifacts": entries,
        "sha256sums_sha256": sha256_file(root / "SHA256SUMS"),
        "raw_data_immutable_after_seal": True,
        "simulated_measurement_accepted": False,
        "publication_performed": False,
    }
    write_json(root / "MANIFEST.json", manifest)
    return manifest


def verify_campaign(directory: Path) -> dict[str, Any]:
    root = Path(directory)
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("invalid campaign manifest schema")
    observed = set()
    for item in manifest["artifacts"]:
        path = root / item["path"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"campaign artifact differs: {item['path']}")
        observed.add(item["path"])
    if sha256_file(root / "SHA256SUMS") != manifest["sha256sums_sha256"]:
        raise ValueError("SHA256SUMS differs from manifest")
    expected = {
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name not in {"MANIFEST.json", "SHA256SUMS"}
    }
    if observed != expected:
        raise ValueError("campaign manifest file set differs")
    return {"status": "PASS", "artifacts": len(observed), "manifest_sha256": sha256_file(root / "MANIFEST.json")}
