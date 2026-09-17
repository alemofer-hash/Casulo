from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


OLD_MANIFEST = "7a8b4c4f2e7538c40347ead4a9caed68b7031419695bad28d93c0919d10d13f2"
OLD_LAUNCHER = "1d9b9880346b341c14bec682d390471a09d473bc8b0a7442b34981154a7bef0d"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output exists; overwrite denied")
    output.mkdir(parents=True)
    release = repo / "release/human-proof"
    old = repo / "release/human-proof-superseded-vbscript-utf8-bom-attempt2"
    prior_rc12 = repo / "product-demos/revolution-closure/rc12-release/gate.json"
    prior_rc13 = repo / "product-demos/revolution-closure/rc13-handoff/gate.json"
    environment = os.environ.copy()
    environment["CASULO_LAUNCHER_DRY_RUN"] = "1"
    launchers: list[dict[str, object]] = []
    for launcher in sorted(release.glob("*.vbs")):
        raw = launcher.read_bytes()
        completed = subprocess.run(
            ["cscript.exe", "//nologo", str(launcher)], env=environment,
            capture_output=True, text=True, encoding="cp1252", errors="replace",
            check=False, shell=False,
        )
        launchers.append({
            "name": launcher.name, "first_bytes_hex": raw[:4].hex(" "),
            "utf8_bom_absent": not raw.startswith(b"\xef\xbb\xbf"),
            "utf16_bom_absent": not raw.startswith((b"\xff\xfe", b"\xfe\xff")),
            "exit_code": completed.returncode, "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(), "sha256": sha256(launcher),
        })
    verify = subprocess.run(
        [os.fspath(Path(os.sys.executable)), "tools/human_proof_control.pyw", "verify", "--release", "release/human-proof", "--json"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False,
    )
    verification = json.loads(verify.stdout)
    regression = subprocess.run(
        [os.fspath(Path(os.sys.executable)), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(output / "pytest-temp"), "tests/product/test_human_proof_release.py"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False,
    )
    (output / "regression.txt").write_text(regression.stdout + regression.stderr, encoding="utf-8", newline="\n")
    checks = {
        "old_manifest_preserved": sha256(old / "MANIFEST.json") == OLD_MANIFEST,
        "old_launcher_preserved": sha256(old / "START_CASULO_OWNER.vbs") == OLD_LAUNCHER,
        "old_failure_reproduced_by_bytes": (old / "START_CASULO_OWNER.vbs").read_bytes().startswith(b"\xef\xbb\xbf"),
        "four_launchers": len(launchers) == 4,
        "all_bom_free": all(item["utf8_bom_absent"] and item["utf16_bom_absent"] for item in launchers),
        "all_parse_in_real_wsh": all(item["exit_code"] == 0 and item["stdout"] == "CASULO_VBS_PARSE_PASS" for item in launchers),
        "release_signature_and_hashes": verify.returncode == 0 and verification.get("ready") is True,
        "focused_regression": regression.returncode == 0 and "5 passed" in regression.stdout,
        "base_unchanged": sha256(release / "OWNER_VM/casulo-native-generative-interactive.img") == "74fe4b1130b40f5090c9944acdd4da0b86c122ab99be5a6b314f61a7e22b810b",
        "owner_artifact_unchanged": sha256(release / "OWNER_VM/casulo-owner-generative-semantic-multiverse.zip") == "547cc4047b5d7523dae28960dbaa67971bdf952ece4a9e7b2a9f14a9104f6a9a",
        "prior_gates_preserved": prior_rc12.is_file() and prior_rc13.is_file(),
        "storage_reserve": shutil.disk_usage(repo).free >= 25 * 1024**3,
    }
    captured = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema": "casulo.revolution-closure-launcher-reseal/1.0",
        "state": "READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF" if all(checks.values()) else "IN_PROGRESS_CHECKPOINTED",
        "gate": "RC13_HANDOFF_COMPLETE_VBSCRIPT_RESEAL",
        "checks": checks,
        "launchers": launchers,
        "verification": verification,
        "old_manifest_sha256": OLD_MANIFEST,
        "new_manifest_sha256": sha256(release / "MANIFEST.json"),
        "new_signature_sha256": sha256(release / "MANIFEST.json.sig"),
        "new_sha256sums_sha256": sha256(release / "SHA256SUMS"),
        "prior_rc12_gate_sha256": sha256(prior_rc12),
        "prior_rc13_gate_sha256": sha256(prior_rc13),
        "failure": {"line": 1, "character": 1, "code": "800A0408", "message": "Invalid character", "work_started": False},
        "timestamp": captured,
    }
    write(output / "launcher-reseal.json", receipt)
    write(output / "gate.json", {
        "schema": "casulo.revolution-closure/1.0/gate", "gate_id": receipt["gate"],
        "status": "PASS" if all(checks.values()) else "FAIL", "state": receipt["state"],
        "checks": checks, "release_manifest_sha256": receipt["new_manifest_sha256"],
        "supersedes_manifest_sha256": OLD_MANIFEST, "timestamp": captured,
    })
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
