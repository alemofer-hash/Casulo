from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, asset: dict[str, Any]) -> None:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("asset regular ausente")
    if path.stat().st_size != asset["bytes"] or sha256(path) != asset["sha256"]:
        raise RuntimeError(f"asset diverge do manifesto: {path.name}")


def receive(asset: dict[str, Any], destination: Path, minimum_free: int) -> None:
    if destination.exists():
        verify(destination, asset)
        return
    partial = destination.with_name(destination.name + ".part")
    consecutive_failures = 0
    while True:
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == asset["bytes"]:
            break
        end = min(offset + 64 * 1024 * 1024 - 1, asset["bytes"] - 1)
        headers = {
            "User-Agent": "Casulo-Day2-Bootstrap/1.0",
            "Range": f"bytes={offset}-{end}",
        }
        request = urllib.request.Request(asset["url"], headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 206:
                    raise RuntimeError("servidor recusou intervalo seguro")
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-{end}/"):
                    raise RuntimeError("Content-Range incompatível com o .part")
                mode = "ab" if offset else "xb"
                with partial.open(mode) as output:
                    remaining = end - offset + 1
                    while remaining:
                        chunk = response.read(min(4 * 1024 * 1024, remaining))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                        if partial.stat().st_size > asset["bytes"]:
                            raise RuntimeError("download excedeu o tamanho congelado")
                        if shutil.disk_usage(destination.parent).free < minimum_free:
                            raise RuntimeError("reserva permanente de 30 GiB violada")
        except (TimeoutError, OSError) as error:
            consecutive_failures += 1
            if consecutive_failures == 20:
                raise RuntimeError("download não concluiu após 20 retomadas") from error
            time.sleep(min(consecutive_failures, 5))
            continue
        if partial.stat().st_size == offset:
            consecutive_failures += 1
            if consecutive_failures == 20:
                raise RuntimeError("download sem progresso após 20 retomadas")
            time.sleep(min(consecutive_failures, 5))
        else:
            consecutive_failures = 0
    verify(partial, asset)
    partial.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap oficial Qwen2.5 7B do Day 2")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    minimum_free = int(manifest["minimum_free_bytes"])
    frozen = manifest["resource_fit_model"]
    model_dir = args.cache_root / "models" / "qwen2.5-7b-instruct"
    license_dir = args.cache_root / "licenses"
    model_dir.mkdir(parents=True, exist_ok=True)
    license_dir.mkdir(parents=True, exist_ok=True)
    assets = [
        asset
        for candidate in frozen["candidates"].values()
        for asset in candidate["files"]
    ]
    for asset in assets:
        receive(asset, model_dir / asset["file"], minimum_free)

    license_path = license_dir / "Apache-2.0.txt"
    if not license_path.exists():
        request = urllib.request.Request(
            frozen["license_url"], headers={"User-Agent": "Casulo-Day2-Bootstrap/1.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response, license_path.open("xb") as output:
            output.write(response.read(1024 * 1024))
    if (
        not license_path.is_file()
        or license_path.stat().st_size != frozen["license_bytes"]
        or sha256(license_path) != frozen["license_sha256"]
    ):
        raise RuntimeError("licença Apache-2.0 diverge do manifesto")

    receipt = {
        "schema": "casulo.family.day2-qwen25-installation/1.0",
        "installed_at_utc": datetime.now(UTC).isoformat(),
        "repository": frozen["repository"],
        "revision": frozen["revision"],
        "license": frozen["license"],
        "license_file": license_path.name,
        "license_sha256": sha256(license_path),
        "files": [
            {
                "path": str((model_dir / item["file"]).relative_to(args.cache_root)).replace("\\", "/"),
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in assets
        ],
        "free_bytes_after": shutil.disk_usage(args.cache_root).free,
        "minimum_free_bytes": minimum_free,
        "rollback": "Stop Casulo processes, then remove only models/qwen2.5-7b-instruct and this receipt.",
    }
    receipt_path = args.cache_root / "QWEN25_INSTALLATION.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    sbom_path = args.cache_root / "SBOM.spdx.json"
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    package = {
        "SPDXID": "SPDXRef-Qwen2.5-7B-Instruct-GGUF",
        "name": "Qwen2.5-7B-Instruct-GGUF",
        "versionInfo": frozen["revision"],
        "downloadLocation": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF",
        "licenseConcluded": frozen["license"],
    }
    packages = sbom.setdefault("packages", [])
    if not any(item.get("SPDXID") == package["SPDXID"] for item in packages):
        packages.append(package)
        sbom_path.write_text(json.dumps(sbom, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "QWEN25_ASSETS_VERIFIED", "receipt": str(receipt_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
