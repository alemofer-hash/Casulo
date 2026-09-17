from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Casulo Native owner-alpha doctor")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    if ROOT.resolve() not in bundle.parents or not bundle.is_dir():
        raise SystemExit("bundle must be a repository directory")
    manifest_path = bundle / "MANIFEST.json"
    signature_path = bundle / "MANIFEST.json.sig"
    signature_meta_path = bundle / "DEVELOPMENT_SIGNATURE.json"
    allowed = bundle / "allowed_signers"
    sums_path = bundle / "SHA256SUMS"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    signature_meta = json.loads(signature_meta_path.read_text(encoding="utf-8"))
    file_checks = {
        item["path"]: (
            (bundle / item["path"]).is_file()
            and (bundle / item["path"]).stat().st_size == item["bytes"]
            and sha256(bundle / item["path"]) == item["sha256"]
        )
        for item in manifest["files"]
    }
    sums_checks: dict[str, bool] = {}
    for line in sums_path.read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        path = bundle / name
        sums_checks[name] = path.is_file() and sha256(path) == digest
    verify = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", "casulo-native-owner-alpha", "-n", "casulo-native-owner-alpha", "-s", str(signature_path)],
        input=manifest_path.read_text(encoding="utf-8"), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    image = bundle / manifest["image"]["file"]
    with image.open("rb") as handle:
        handle.seek(510)
        boot_signature = handle.read(2)
    checks = {
        "state_delimited": manifest.get("state") == "FLASHABLE_PREVIEW_NOT_CONVERSATIONAL",
        "manifest_files": all(file_checks.values()),
        "sha256sums": all(sums_checks.values()),
        "development_signature_label": signature_meta.get("label") == "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE",
        "development_signature_verified": verify.returncode == 0,
        "manifest_signature_binding": signature_meta.get("manifest_sha256") == sha256(manifest_path),
        "image_hash": sha256(image) == manifest["image"]["sha256"],
        "boot_sector_signature": boot_signature == b"\x55\xaa",
        "virtual_usb_gate": manifest.get("virtual_usb_gate", {}).get("passed") is True,
        "network_off": manifest.get("guest_network_default") == "OFF",
        "cloud_locked": manifest.get("cloud") == "RELEASE_LOCKED",
        "no_physical_write": manifest.get("physical_device_written") is False,
        "no_false_neural_token": manifest.get("first_model_derived_token") is False,
        "model_not_embedded": manifest.get("model_embedded") is False,
    }
    report = {
        "schema": "casulo-native-owner-alpha-doctor/0.1",
        "bundle": bundle.relative_to(ROOT).as_posix(),
        "checks": checks,
        "file_checks": file_checks,
        "sums_checks": sums_checks,
        "signature_output": verify.stdout.strip(),
        "state": "NATIVE_OWNER_ALPHA_PREVIEW_VALIDATED" if all(checks.values()) else "INVALID",
        "native_neural_conversation": "BLOCKED_NATIVE_QWEN_RUNTIME_PORT",
        "physical_flash": "NOT_EXECUTED",
        "passed": all(checks.values()),
    }
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents:
        raise SystemExit("output must remain inside repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
