from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restrict_private_file(path: Path) -> str:
    os.chmod(path, 0o600)
    if os.name != "nt":
        return "chmod-0600"
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    sid = next(csv.reader([identity]))[1]
    subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(F)",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return f"windows-acl-owner-only:{sid}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap owner-only Casulo TLS")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--host", action="append", required=True)
    args = parser.parse_args()
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True)
    targets = {
        "ca_key": state / "casulo-family-ca-key.pem",
        "ca_cert": state / "casulo-family-ca.pem",
        "server_key": state / "casulo-family-server-key.pem",
        "server_cert": state / "casulo-family-server.pem",
        "owner_token": state / "owner-token.txt",
        "manifest": state / "tls-manifest.json",
    }
    occupied = [str(path) for path in targets.values() if path.exists()]
    if occupied:
        raise FileExistsError(f"bootstrap não sobrescreve arquivos: {occupied}")

    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Casulo Family Local CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key = ec.generate_private_key(ec.SECP256R1())
    san: list[x509.GeneralName] = []
    normalized_hosts: list[str] = []
    for host in dict.fromkeys(args.host):
        try:
            value = ipaddress.ip_address(host)
            san.append(x509.IPAddress(value))
            normalized_hosts.append(str(value))
        except ValueError:
            if not host or len(host) > 253 or any(ch.isspace() for ch in host):
                raise ValueError(f"hostname inválido: {host!r}")
            san.append(x509.DNSName(host))
            normalized_hosts.append(host)
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, normalized_hosts[0])]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    targets["ca_key"].write_bytes(
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    targets["server_key"].write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    targets["ca_cert"].write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    targets["server_cert"].write_bytes(
        server_cert.public_bytes(serialization.Encoding.PEM)
    )
    targets["owner_token"].write_text(
        secrets.token_urlsafe(48) + "\n", encoding="ascii", newline="\n"
    )
    acl = {
        name: restrict_private_file(targets[name])
        for name in ("ca_key", "server_key", "owner_token")
    }
    manifest = {
        "schema": "casulo.family.day4-tls-bootstrap/1.0",
        "created_utc": now.isoformat(),
        "hosts": normalized_hosts,
        "algorithm": "ECDSA-P256-SHA256",
        "cryptography_version": version("cryptography"),
        "cryptography_license": "Apache-2.0 OR BSD-3-Clause",
        "private_files_outside_git": True,
        "private_file_acl": acl,
        "ca_certificate_sha256": sha256(targets["ca_cert"]),
        "server_certificate_sha256": sha256(targets["server_cert"]),
        "root_installation_performed": False,
    }
    targets["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "state_dir": str(state),
                "ca_certificate": str(targets["ca_cert"]),
                "server_certificate": str(targets["server_cert"]),
                "owner_token_printed": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
