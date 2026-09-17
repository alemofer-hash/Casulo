from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Edition:
    name: str
    project: Path
    redistributable: bool
    license_id: str
    engine_boundary: str


EDITIONS = {
    "owner": Edition(
        "casulo-owner",
        ROOT / "private/casulo-owner",
        False,
        "LicenseRef-Teloscorp-Proprietary",
        "owner-direct-first-party",
    ),
    "public": Edition(
        "casulo-public",
        ROOT / "editions/casulo-public",
        True,
        "MIT",
        "cloud-client-only-no-owner-fallback",
    ),
    "cloud-standby": Edition(
        "casulo-cloud-standby",
        ROOT / "services/casulo-cloud-standby",
        False,
        "LicenseRef-Teloscorp-Proprietary",
        "server-private-release-locked",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_edition(profile: str, output_root: Path, signing_key: Path) -> dict[str, object]:
    edition = EDITIONS[profile]
    destination = (output_root / profile).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError(f"release destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(destination),
            str(edition.project),
        ],
        cwd=ROOT,
        check=True,
    )
    wheels = tuple(destination.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("edition build must produce exactly one wheel")
    wheel = wheels[0]
    public_audit: dict[str, object] | None = None
    if profile == "public":
        import importlib.util

        spec = importlib.util.spec_from_file_location("audit_public_artifact", ROOT / "tools/audit_public_artifact.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        public_audit = module.audit(wheel)
        if not public_audit["private_components_absent"]:
            raise RuntimeError("public artifact audit failed")
        (destination / "PUBLIC_AUDIT.json").write_text(
            json.dumps(public_audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{edition.name}-product-alpha",
        "documentNamespace": f"https://teloscorp.invalid/spdx/{edition.name}/0.1.0a1",
        "creationInfo": {"created": "2026-08-11T00:00:00Z", "creators": ["Organization: Teloscorp"]},
        "packages": [
            {
                "name": edition.name,
                "SPDXID": "SPDXRef-Package-Edition",
                "versionInfo": "0.1.0a1",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": edition.license_id,
                "checksums": [{"algorithm": "SHA256", "checksumValue": sha256(wheel)}],
            }
        ],
        "files": [
            {
                "fileName": wheel.name,
                "SPDXID": "SPDXRef-File-Wheel",
                "checksums": [{"algorithm": "SHA256", "checksumValue": sha256(wheel)}],
            }
        ],
    }
    sbom_path = destination / "SBOM.spdx.json"
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    public_key = signing_key.with_suffix(signing_key.suffix + ".pub")
    if not signing_key.is_file() or not public_key.is_file():
        raise RuntimeError("explicit edition signing key and public key are required")
    fingerprint = subprocess.run(
        ["ssh-keygen", "-lf", str(public_key), "-E", "sha256"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[1]
    manifest = {
        "schema": "casulo-product-edition-release/1.0",
        "profile": profile,
        "package": edition.name,
        "redistributable": edition.redistributable,
        "engine_boundary": edition.engine_boundary,
        "wheel": {"file": wheel.name, "sha256": sha256(wheel)},
        "sbom": {"file": sbom_path.name, "sha256": sha256(sbom_path)},
        "signing": {
            "algorithm": "ssh-ed25519",
            "namespace": "casulo-release",
            "identity": f"casulo-{profile}-dev",
            "public_key_fingerprint": fingerprint,
            "development_key": True,
        },
        "release_state": "RELEASE_LOCKED" if profile == "cloud-standby" else "PRODUCT_ALPHA_LOCAL",
        "production_eligible": False,
        "public_audit": public_audit,
    }
    manifest_path = destination / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(signing_key), "-n", "casulo-release", str(manifest_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    signature = manifest_path.with_suffix(manifest_path.suffix + ".sig")
    copied_public = destination / "SIGNING_KEY.pub"
    copied_public.write_bytes(public_key.read_bytes())
    identity = f"casulo-{profile}-dev"
    allowed = destination / "ALLOWED_SIGNERS"
    allowed.write_text(f"{identity} {public_key.read_text(encoding='ascii').strip()}\n", encoding="ascii")
    verified = subprocess.run(
        [
            "ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", identity,
            "-n", "casulo-release", "-s", str(signature),
        ],
        input=manifest_path.read_text(encoding="utf-8"),
        check=True,
        capture_output=True,
        text=True,
    )
    verification = destination / "SIGNATURE_VERIFICATION.txt"
    verification.write_text(verified.stdout + verified.stderr, encoding="utf-8")
    sums_path = destination / "SHA256SUMS"
    payloads = sorted(item for item in destination.iterdir() if item.is_file() and item != sums_path)
    sums_path.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in payloads),
        encoding="ascii",
        newline="\n",
    )
    return {
        "profile": profile,
        "wheel": str(wheel),
        "wheel_sha256": sha256(wheel),
        "manifest_sha256": sha256(manifest_path),
        "signature_verified": True,
        "public_audit_pass": None if public_audit is None else public_audit["private_components_absent"],
        "release_state": manifest["release_state"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build separately signed Casulo product editions")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-key", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--cloud-key", type=Path, required=True)
    args = parser.parse_args()
    keys = {"owner": args.owner_key, "public": args.public_key, "cloud-standby": args.cloud_key}
    results = [build_edition(profile, args.output.resolve(), keys[profile].resolve()) for profile in EDITIONS]
    print(json.dumps({"schema": "casulo-product-editions/1.0", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
