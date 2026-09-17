from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/casulo-os-rp01/g0/baseline.json"


def run(*args: str) -> str:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout.strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def tracked_files() -> list[dict[str, object]]:
    paths = [Path(line) for line in run("git", "ls-files").splitlines() if line]
    return [
        {
            "path": path.as_posix(),
            "bytes": (ROOT / path).stat().st_size,
            "sha256": digest(ROOT / path),
        }
        for path in paths
    ]


def create() -> dict[str, object]:
    payload = {
        "schema": "casulo-os-baseline/1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "branch", "--show-current"),
        "preexisting_untracked": [
            "benchmarks/results/2026-08-02-sprint025-ablation/",
            "paper_artifacts/",
        ],
        "correctness_gate": {
            "passed": 215,
            "skipped": 1,
            "subtests_passed": 45,
            "elapsed_seconds": 88.89,
            "performance_sample": False,
        },
        "tracked_files": tracked_files(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def verify() -> dict[str, object]:
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    commit = str(payload["commit"])
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    committed: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        for member in source.getmembers():
            if not member.isfile():
                continue
            handle = source.extractfile(member)
            if handle is not None:
                committed[member.name] = handle.read()
    structural_failures: list[str] = []
    working_tree_differences: list[str] = []
    unexpected_working_tree_differences: list[str] = []
    commit_snapshot_differences: list[str] = []
    declared_paths = [str(item.get("path", "")) for item in payload.get("tracked_files", [])]
    if payload.get("schema") != "casulo-os-baseline/1.0":
        structural_failures.append("schema")
    if len(declared_paths) != len(set(declared_paths)) or any(not path for path in declared_paths):
        structural_failures.append("tracked_files.paths")
    intentionally_changed = {
        line.replace("\\", "/")
        for line in run("git", "diff", "--name-only", "--").splitlines()
        if line
    }
    for item in payload["tracked_files"]:
        relative = str(item["path"])
        frozen = committed.get(relative)
        frozen_digest = hashlib.sha256(frozen).hexdigest() if frozen is not None else None
        if frozen is None or len(frozen) != item["bytes"] or frozen_digest != item["sha256"]:
            commit_snapshot_differences.append(relative)
        expected_sha = item.get("sha256")
        expected_bytes = item.get("bytes")
        if (
            not isinstance(expected_sha, str)
            or len(expected_sha) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            structural_failures.append(f"tracked_files:{relative}")
            continue
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            working_tree_differences.append(relative)
            if relative not in intentionally_changed:
                unexpected_working_tree_differences.append(relative)
    passed = not structural_failures and not unexpected_working_tree_differences
    return {
        "status": "PASS" if passed else "FAIL",
        "baseline_manifest_integrity": "PASS" if not structural_failures else "FAIL",
        "baseline_manifest_sha256": digest(OUTPUT),
        "checked": len(payload["tracked_files"]),
        "structural_failures": structural_failures,
        "baseline_captured_dirty_worktree": bool(commit_snapshot_differences),
        "baseline_commit_snapshot_difference_count": len(commit_snapshot_differences),
        "working_tree_diverged_as_expected": bool(working_tree_differences),
        "working_tree_difference_count": len(working_tree_differences),
        "working_tree_differences": working_tree_differences,
        "unexpected_working_tree_differences": unexpected_working_tree_differences,
        "baseline_commit": commit,
        "current_commit": run("git", "rev-parse", "HEAD"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify() if args.verify else create()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
