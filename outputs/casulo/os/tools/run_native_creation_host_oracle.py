#!/usr/bin/env python3
"""Run the bounded NP10 host oracle and persist append-only evidence.

This runner does not infer expected output from the native implementation.  It
compares the first-party decoder against the token sequence frozen previously
with the local llama.cpp bootstrap runtime.  It never contacts a network.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
EXPECTED_OUTPUT_IDS = [
    45, 11408, 28, 8373, 5404, 285, 67737, 436, 26, 62721, 5049, 46,
    28, 8373, 5404, 285, 67737, 436, 26, 1825, 49, 32293, 28, 32615,
    16, 11, 32615, 17, 26, 7778, 51171, 28, 32361, 13,
]
DEFAULT_MODEL = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362/model/Qwen3-4B-Q4_K_M.gguf"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_attempt(root: Path) -> Path:
    candidate = root
    attempt = 2
    while candidate.exists():
        candidate = root.with_name(f"{root.name}-attempt-{attempt}")
        attempt += 1
    candidate.mkdir(parents=True)
    return candidate


def parse_output(lines: list[str]) -> dict[str, object]:
    scalar: dict[str, str] = {}
    tokens: list[dict[str, object]] = []
    token_fields: dict[int, dict[str, object]] = {}
    token_pattern = re.compile(r"^OUTPUT_(\d+)_(ID|TEXT_HEX|HIDDEN_SHA256|ELAPSED_MS)=(.*)$")
    for line in lines:
        match = token_pattern.match(line)
        if match:
            index = int(match.group(1))
            field = match.group(2).lower()
            value: object = match.group(3)
            if field == "id":
                value = int(str(value))
            elif field == "elapsed_ms":
                value = float(str(value))
            token_fields.setdefault(index, {"index": index})[field] = value
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            scalar[key] = value
    for index in sorted(token_fields):
        tokens.append(token_fields[index])
    output_ids = ast.literal_eval(scalar.get("OUTPUT_IDS", "[]"))
    return {
        "prompt_tokens": int(scalar.get("PROMPT_TOKENS", "0")),
        "output_tokens": int(scalar.get("OUTPUT_TOKENS", "0")),
        "output_ids": output_ids,
        "llama_cpp_greedy_match_reported": scalar.get("LLAMA_CPP_GREEDY_MATCH") == "true",
        "elapsed_ms": float(scalar.get("ELAPSED_MS", "nan")),
        "tokens": tokens,
    }


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    model = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_MODEL.resolve()
    binary = repo / "os/target/release/examples/creation_host.exe"
    evidence_root = repo / "outputs/casulo/native-boot-to-creation/2026-08-22-np10"
    evidence_dir = choose_attempt(evidence_root)
    evidence_path = evidence_dir / "creation-host-oracle.json"
    log_path = evidence_dir / "creation-host-oracle.log"
    if not binary.is_file():
        raise SystemExit(f"missing oracle binary: {binary}")
    if not model.is_file():
        raise SystemExit(f"missing model: {model}")
    model_hash_before = sha256_file(model)
    if model_hash_before != MODEL_SHA256:
        raise SystemExit(f"model hash mismatch: {model_hash_before}")

    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started_monotonic = time.monotonic()
    lines: list[str] = []
    with log_path.open("x", encoding="utf-8", newline="\n") as log:
        process = subprocess.Popen(
            [str(binary), str(model)],
            cwd=repo,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
        )
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip("\r\n")
            lines.append(line)
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
        return_code = process.wait()

    parsed = parse_output(lines)
    model_hash_after = sha256_file(model)
    checks = {
        "process_exit_zero": return_code == 0,
        "model_hash_before_exact": model_hash_before == MODEL_SHA256,
        "model_hash_after_unchanged": model_hash_after == model_hash_before,
        "prompt_token_count_exact": parsed["prompt_tokens"] == 50,
        "output_token_count_exact": parsed["output_tokens"] == len(EXPECTED_OUTPUT_IDS),
        "output_ids_match_frozen_llama_cpp_oracle": parsed["output_ids"] == EXPECTED_OUTPUT_IDS,
        "decoder_reported_match": parsed["llama_cpp_greedy_match_reported"] is True,
        "per_token_evidence_complete": len(parsed["tokens"]) == len(EXPECTED_OUTPUT_IDS),
    }
    state = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "schema": "casulo-native-creation-host-oracle/1.0",
        "state": state,
        "scope": "bounded first-party Qwen3-4B greedy decoder host oracle; not performance or energy evidence",
        "started_utc": started_utc,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runner_elapsed_seconds": time.monotonic() - started_monotonic,
        "command": [str(binary), str(model)],
        "return_code": return_code,
        "model": {
            "path": str(model),
            "bytes": model.stat().st_size,
            "sha256_before": model_hash_before,
            "sha256_after": model_hash_after,
        },
        "frozen_external_oracle": {
            "runtime": "local llama.cpp bootstrap only",
            "sampling": "greedy",
            "expected_output_ids": EXPECTED_OUTPUT_IDS,
        },
        "parsed": parsed,
        "checks": checks,
        "constraints": {
            "network_used": False,
            "external_api_used": False,
            "physical_device_written": False,
            "performance_claim_authorized": False,
            "energy_claim_authorized": False,
        },
        "interrupted_predecessor": {
            "preserved_as_history": True,
            "observed_prefill_positions_before_user_interruption": 20,
            "scientific_result": "PARTIAL_NOT_JUDGED",
        },
        "log": log_path.name,
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CREATION_HOST_ORACLE_STATE={state}", flush=True)
    print(f"CREATION_HOST_ORACLE_EVIDENCE={evidence_path}", flush=True)
    return 0 if state == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
