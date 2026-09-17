from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path


EXPECTED = {
    "preserved_archive": (
        "product-demos/semantic-multiverse/inspection-failure-3-einstein-preserved/"
        "owner-data/semantic-creation-1/materialized/creation-38da5088c5e61759-v7.casulo.zip",
        "93650a516d1340c84c15efe9aba5b18064b6f4d7115256f1b6f8bace31c7d9d1",
    ),
    "einstein_evidence": (
        "product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/"
        "einstein-solver-evidence.json",
        "003f5644e8f12a57478f795b799405fede46b23c6b18c4ca6e99000a60d678d5",
    ),
    "einstein_package": (
        "product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/"
        "casulo-owner-einstein-local-solver.casulo.zip",
        "554da5a1341f84077c0434f79b9dacd00ba6d5dd96869a91deb92b93002c7860",
    ),
    "checkpoint_manifest": (
        "product-demos/semantic-multiverse/inspection-failure-3-einstein-rerun/MANIFEST.json",
        "e595c97b86721c3b58b0d2e4ea62771b1cb63c6587ccc9794ef0e33f2b7446fa",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return completed.stdout


def main(repo: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise SystemExit("preflight receipt already exists; overwrite denied")
    status = git(repo, "status", "--short")
    worktrees = git(repo, "worktree", "list", "--porcelain")
    hashes = {}
    for label, (relative, expected) in EXPECTED.items():
        path = repo / relative
        actual = sha256(path) if path.is_file() else None
        hashes[label] = {
            "path": relative,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "matches": actual == expected,
            "bytes": path.stat().st_size if path.is_file() else None,
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat() if path.is_file() else None,
        }
    archive = repo / EXPECTED["preserved_archive"][0]
    receipt = {
        "schema": "casulo.semantic-reseal-preflight/1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "branch": git(repo, "branch", "--show-current").strip(),
        "commit": git(repo, "rev-parse", "HEAD").strip(),
        "worktree_substantially_modified": len(status.splitlines()) >= 20,
        "git_status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "git_status_line_count": len(status.splitlines()),
        "worktrees": worktrees.splitlines(),
        "free_bytes": shutil.disk_usage(repo).free,
        "hashes": hashes,
        "all_received_hashes_match": all(item["matches"] for item in hashes.values()),
        "preserved_archive_read_only_observation": {
            "path": str(archive),
            "sha256": sha256(archive),
            "mutation_authorized": False,
        },
        "historical_evidence_preservation": True,
        "destructive_git_commands_used": False,
        "downloads_or_installs": 0,
        "divergences": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    if not receipt["all_received_hashes_match"]:
        raise SystemExit("received baseline divergence")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.repo.resolve(strict=True), args.output.resolve())
