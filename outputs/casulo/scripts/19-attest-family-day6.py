"""Non-circular manifest sealing and reproducible post-commit Git attestation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
                    encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal-manifest", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    evidence = root/"evidence/family/day6"
    receipt_file = evidence/"final-receipt.json"
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if receipt["status"] != "PASS":
        raise RuntimeError("gate is not PASS")
    if args.seal_manifest:
        hashes = {p.relative_to(evidence).as_posix(): sha(p) for p in sorted(evidence.rglob("*"))
                  if p.is_file() and p.name != "SHA256SUMS.txt" and p != receipt_file}
        report = root/"docs/product/CASULO_FAMILY_RP01_DAY6_CLEO_VOICE_PERSONAS.md"
        hashes["../../../docs/product/"+report.name] = sha(report)
        receipt["evidence_sha256"] = hashes
        write(receipt_file, receipt)
        hashes["final-receipt.json"] = sha(receipt_file)
        (evidence/"SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())),
            encoding="ascii", newline="\n")
        print(json.dumps({"sealed_files": len(hashes), "manifest_sha256": sha(evidence/"SHA256SUMS.txt")}))
        return 0
    if args.output is None:
        parser.error("--output is required for post-commit attestation")
    target = args.output.resolve()
    if target.is_relative_to(repo) or target.exists():
        raise RuntimeError("attestation must be new and outside the Git repository")
    status = git(repo, "status", "--porcelain=v1")
    if status:
        raise RuntimeError("working tree is not clean")
    if git(repo, "remote", "get-url", "origin") != "https://github.com/alemofer-hash/Casulo.git":
        raise RuntimeError("unexpected remote target")
    commit = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    remote = git(repo, "ls-remote", "origin", "refs/heads/rp0.1-family").split()[0]
    if remote != commit:
        raise RuntimeError("remote commit mismatch")
    provider = json.loads(subprocess.run(
        ["gh", "repo", "view", "alemofer-hash/Casulo", "--json", "nameWithOwner,visibility"],
        check=True, capture_output=True, text=True).stdout)
    if provider["visibility"] != "PRIVATE":
        raise RuntimeError("remote not verified PRIVATE")
    fsck = subprocess.run(["git", "fsck", "--full"], cwd=repo, capture_output=True, text=True)
    if fsck.returncode:
        raise RuntimeError("git fsck failed")
    for line in (evidence/"SHA256SUMS.txt").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        if sha(evidence/relative) != digest:
            raise RuntimeError("evidence hash mismatch")
    for relative, digest in receipt["source_sha256"].items():
        if sha(repo/relative) != digest:
            raise RuntimeError("source hash mismatch")
    receipt.update({"final_commit": commit, "final_tree": tree, "remote_reference": "origin/rp0.1-family",
                    "remote_commit": remote, "provider": provider, "working_tree_clean": True,
                    "fsck_exit_code": 0, "fsck_output": fsck.stdout+fsck.stderr,
                    "evidence_manifest_sha256": sha(evidence/"SHA256SUMS.txt")})
    target.parent.mkdir(parents=True, exist_ok=True)
    write(target, receipt)
    print(json.dumps({"status": "PASS", "final_commit": commit, "final_tree": tree,
                      "remote_commit": remote, "visibility": "PRIVATE", "attestation_sha256": sha(target)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
