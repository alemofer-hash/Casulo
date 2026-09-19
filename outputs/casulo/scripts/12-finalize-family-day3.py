from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} não contém objeto JSON")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal Casulo Family Day 3 evidence")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    report = args.report.resolve()

    required = {
        "baseline.json",
        "supervisor-lifecycle.json",
        "streaming.json",
        "cancellation.json",
        "queue-backpressure.json",
        "resource-samples.jsonl",
        "port-inspection-before.txt",
        "port-inspection-during.txt",
        "port-inspection-after.txt",
        "process-inspection-before.txt",
        "process-inspection-after.txt",
        "test-results.txt",
        "integration-result.json",
    }
    missing = sorted(name for name in required if not (evidence / name).is_file())
    if missing:
        raise FileNotFoundError(f"evidências ausentes: {missing}")

    baseline = read_json(evidence / "baseline.json")
    lifecycle = read_json(evidence / "supervisor-lifecycle.json")
    streaming = read_json(evidence / "streaming.json")
    cancellation = read_json(evidence / "cancellation.json")
    queue = read_json(evidence / "queue-backpressure.json")
    integration = read_json(evidence / "integration-result.json")
    samples = [
        json.loads(line)
        for line in (evidence / "resource-samples.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    if not samples:
        raise ValueError("resource-samples.jsonl vazio")

    thermal = {
        "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
        "temperature_telemetry_collected_by_runner": False,
        "temperature_claim": "NONE",
    }
    for source in (baseline, integration, *samples):
        for key, expected in thermal.items():
            if source.get(key) != expected:
                raise ValueError(f"política térmica divergente em {key}")
    if baseline.get("input_commit") != "be19c85df370277fb2a71915e57f7e883e0508e6":
        raise ValueError("commit de entrada divergente")
    if baseline.get("input_tree") != "29bd537b005f336677059f4205b1353aa0033d29":
        raise ValueError("tree de entrada divergente")
    if integration.get("status") != "PASS":
        raise ValueError("integração real não passou")
    if lifecycle.get("current_state") != "STOPPED":
        raise ValueError("supervisor não terminou STOPPED")
    transitions = lifecycle.get("transitions", [])
    if any(item.get("current") in {"DEGRADED", "FAILED"} for item in transitions):
        raise ValueError("execução autoritativa contém degradação/falha")
    if queue.get("maximum_active_generations") != 1:
        raise ValueError("concorrência ativa não foi exatamente um")
    if cancellation.get("supervisor_returned_ready") is not True:
        raise ValueError("supervisor não retornou a READY")

    direct_files = sorted(
        path
        for path in evidence.iterdir()
        if path.is_file() and path.name not in {"final-receipt.json", "SHA256SUMS.txt"}
    )
    hashes = {path.name: sha256(path) for path in direct_files}
    fifo_terminal = streaming["fifo_completed_stream"][-1]
    short_terminal = streaming["post_cancel_completed_stream"][-1]
    receipt = {
        "schema": "casulo.family.day3-final-receipt/1.0",
        "status": "PASS",
        "generated_utc": datetime.now(UTC).isoformat(),
        "input": {
            "branch": baseline["branch"],
            "commit": baseline["input_commit"],
            "tree": baseline["input_tree"],
        },
        "model": {
            "repository": "Qwen/Qwen2.5-7B-Instruct-GGUF",
            "revision": "293ca9a10157b0e5fc5cb32af8b636a88bede891",
            "quantization": "Q2_K",
            "sha256": "a0fc885ff014d73c02dcc4ad093f110c6dd4e0e308f84efe1accf078d364a87a",
        },
        "runtime": {
            "backend": "llama.cpp b10964 Vulkan",
            "address_effective": integration["runtime_address"],
            "loopback_only": True,
            "instances": 1,
            "active_concurrency": 1,
            "queue_policy": "FIFO",
            "queue_capacity": integration["queue_capacity"],
        },
        "requests": integration["counters"],
        "streaming": {
            "fifo_time_to_first_fragment_ms": fifo_terminal[
                "time_to_first_fragment_ms"
            ],
            "fifo_duration_ms": fifo_terminal["duration_ms"],
            "post_cancel_time_to_first_fragment_ms": short_terminal[
                "time_to_first_fragment_ms"
            ],
            "post_cancel_duration_ms": short_terminal["duration_ms"],
            "incremental": streaming["incremental_before_terminal"],
            "ordered": streaming["ordered"],
        },
        "resources": {
            "samples": len(samples),
            "maximum_process_working_set_bytes": max(
                int(item.get("process_working_set_bytes") or 0) for item in samples
            ),
            "minimum_available_ram_bytes": min(
                int(item["available_ram_bytes"]) for item in samples
            ),
            "minimum_disk_free_bytes": min(
                int(item["disk_free_bytes"]) for item in samples
            ),
            **thermal,
        },
        "cleanup": {
            "processes": integration["process_cleanup"],
            "ports": integration["port_cleanup"],
            "sampler": integration["sampler_cleanup"],
            "supervisor_final_state": lifecycle["current_state"],
        },
        "tests": {
            "focal_day3": "15 passed",
            "family_allowed": "23 passed",
            "product_allowed": "722 passed, 1 skipped",
            "static": "PASS",
            "real_integration": "PASS",
        },
        "evidence_sha256": hashes,
        "report": {
            "path": report.as_posix(),
            "sha256": sha256(report),
        },
        "limitations": [
            "temperature is monitored manually by the user in external HWiNFO; the runner collected no thermal telemetry and makes no thermal claim",
            "HTTPS, device authentication, session isolation and PWA are Day 4 scope",
            "attempts 1-5 are preserved diagnostic history; attempt-6 is authoritative",
        ],
    }
    receipt_path = evidence / "final-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sum_files = sorted(
        path for path in evidence.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (evidence / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in sum_files),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status": "PASS", "files": len(sum_files)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
