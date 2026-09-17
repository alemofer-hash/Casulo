from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .chunking import FixedChunkingPolicy, iter_fixed_chunks
from .codecs import CodecError, decode_chunk, encode_chunk

SCHEMA = "casulo.lossless-archive/0.1"
AUTHOR = "G Moura Fernandes / Teloscorp"
MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_CHUNKS = 10_000_000
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class CompressionError(RuntimeError):
    """Falha fechada no empacotamento, verificação ou reconstrução."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    return info


def pack_file(
    source: str | Path,
    archive: str | Path,
    *,
    profile: str = "balanced",
    chunk_size: int = 4 * 1024 * 1024,
) -> dict[str, Any]:
    """Empacota uma fonte em streaming e confirma a reconstrução antes do PASS."""

    source_path = Path(source).resolve(strict=True)
    archive_path = Path(archive).resolve(strict=False)
    if not source_path.is_file():
        raise CompressionError("a fonte precisa ser um arquivo regular")
    if archive_path.exists():
        raise CompressionError(f"destino já existe: {archive_path}")
    if source_path == archive_path:
        raise CompressionError("fonte e destino não podem ser o mesmo arquivo")

    policy = FixedChunkingPolicy(chunk_size=chunk_size)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    source_before = source_path.stat()
    source_hash = hashlib.sha256()
    sequence: list[str] = []
    chunks: dict[str, dict[str, Any]] = {}
    source_size = 0
    unique_raw_bytes = 0
    stored_payload_bytes = 0

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{archive_path.name}.",
        suffix=".partial",
        dir=archive_path.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with source_path.open("rb") as source_stream, zipfile.ZipFile(
            temporary_path,
            "w",
            allowZip64=True,
        ) as output:
            for raw in iter_fixed_chunks(source_stream, policy):
                source_hash.update(raw)
                source_size += len(raw)
                digest = _sha256(raw)
                sequence.append(digest)
                if digest in chunks:
                    continue

                encoded = encode_chunk(raw, profile=profile)
                output.writestr(_zip_info(f"chunks/{digest}.bin"), encoded.payload)
                chunks[digest] = {
                    "codec": encoded.codec,
                    "payload_sha256": _sha256(encoded.payload),
                    "raw_size": len(raw),
                    "stored_size": len(encoded.payload),
                }
                unique_raw_bytes += len(raw)
                stored_payload_bytes += len(encoded.payload)

            source_after = source_path.stat()
            if (
                source_before.st_size != source_after.st_size
                or source_before.st_mtime_ns != source_after.st_mtime_ns
            ):
                raise CompressionError("a fonte mudou durante o empacotamento")

            manifest: dict[str, Any] = {
                "schema": SCHEMA,
                "author": AUTHOR,
                "source": {
                    "name": source_path.name,
                    "sha256": source_hash.hexdigest(),
                    "size": source_size,
                },
                "policy": {
                    "codec_profile": profile,
                    "chunking": policy.as_dict(),
                },
                "sequence": sequence,
                "chunks": chunks,
                "accounting": {
                    "chunk_references": len(sequence),
                    "unique_chunks": len(chunks),
                    "unique_raw_bytes": unique_raw_bytes,
                    "stored_payload_bytes": stored_payload_bytes,
                    "deduplicated_bytes": source_size - unique_raw_bytes,
                },
            }
            output.writestr(_zip_info(MANIFEST_NAME), _canonical_json(manifest))
        os.replace(temporary_path, archive_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    result = verify_archive(archive_path)
    archive_size = archive_path.stat().st_size
    result.update(
        {
            "archive": str(archive_path),
            "archive_sha256": _sha256_file(archive_path),
            "archive_bytes": archive_size,
            "container_ratio": None if source_size == 0 else archive_size / source_size,
            "reduction_percent": None
            if source_size == 0
            else (1.0 - archive_size / source_size) * 100.0,
        }
    )
    return result


def _load_manifest(
    archive_path: Path,
) -> tuple[zipfile.ZipFile, dict[str, Any], bytes]:
    try:
        package = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CompressionError("contêiner Casulo inválido") from exc

    try:
        names = [info.filename for info in package.infolist()]
        if len(names) != len(set(names)):
            raise CompressionError("entradas duplicadas no contêiner")
        if MANIFEST_NAME not in names:
            raise CompressionError("manifest.json ausente")
        info = package.getinfo(MANIFEST_NAME)
        if info.compress_type != zipfile.ZIP_STORED:
            raise CompressionError("manifest usa camada ZIP não autorizada")
        if info.file_size > MAX_MANIFEST_BYTES:
            raise CompressionError("manifest excede o limite")
        manifest_bytes = package.read(MANIFEST_NAME)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise CompressionError("manifest precisa ser um objeto")
        return package, manifest, manifest_bytes
    except Exception:
        package.close()
        raise


def _require_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompressionError(f"{field} precisa ser inteiro")
    return value


def _derived_accounting(manifest: Mapping[str, Any]) -> dict[str, int]:
    chunks = manifest["chunks"]
    sequence = manifest["sequence"]
    source_size = manifest["source"]["size"]
    unique_raw_bytes = sum(metadata["raw_size"] for metadata in chunks.values())
    stored_payload_bytes = sum(
        metadata["stored_size"] for metadata in chunks.values()
    )
    return {
        "chunk_references": len(sequence),
        "unique_chunks": len(chunks),
        "unique_raw_bytes": unique_raw_bytes,
        "stored_payload_bytes": stored_payload_bytes,
        "deduplicated_bytes": source_size - unique_raw_bytes,
    }


def _validate_manifest(manifest: Mapping[str, Any], package: zipfile.ZipFile) -> None:
    if manifest.get("schema") != SCHEMA:
        raise CompressionError(f"schema incompatível: {manifest.get('schema')!r}")
    source = manifest.get("source")
    chunks = manifest.get("chunks")
    sequence = manifest.get("sequence")
    policy = manifest.get("policy")
    if not isinstance(source, dict) or not isinstance(chunks, dict):
        raise CompressionError("source/chunks obrigatórios ausentes")
    if not isinstance(sequence, list) or not isinstance(policy, dict):
        raise CompressionError("sequence/policy obrigatórios ausentes")
    if len(chunks) > MAX_CHUNKS or len(sequence) > MAX_CHUNKS:
        raise CompressionError("quantidade de chunks excede o limite")

    chunking = policy.get("chunking")
    if not isinstance(chunking, dict) or chunking.get("algorithm") != "fixed-v1":
        raise CompressionError("algoritmo de chunking incompatível")
    chunk_size = _require_int(chunking.get("chunk_size"), field="chunk_size")
    try:
        FixedChunkingPolicy(chunk_size)
    except ValueError as exc:
        raise CompressionError(str(exc)) from exc
    source_size = _require_int(source.get("size"), field="source.size")
    if source_size < 0:
        raise CompressionError("source.size negativo")
    if not isinstance(source.get("sha256"), str) or not SHA256_PATTERN.fullmatch(
        source["sha256"]
    ):
        raise CompressionError("SHA-256 da fonte inválido")

    expected_names = {MANIFEST_NAME}
    for digest, metadata in chunks.items():
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            raise CompressionError("identidade de chunk inválida")
        if not isinstance(metadata, dict):
            raise CompressionError("metadados de chunk inválidos")
        raw_size = _require_int(metadata.get("raw_size"), field="chunk.raw_size")
        stored_size = _require_int(metadata.get("stored_size"), field="chunk.stored_size")
        if raw_size < 0 or raw_size > chunk_size or stored_size < 0 or stored_size > raw_size:
            raise CompressionError("limite de chunk violado")
        if metadata.get("codec") not in {"raw", "zlib", "lzma"}:
            raise CompressionError("codec de chunk inválido")
        payload_hash = metadata.get("payload_sha256")
        if not isinstance(payload_hash, str) or not SHA256_PATTERN.fullmatch(payload_hash):
            raise CompressionError("SHA-256 de payload inválido")

        name = f"chunks/{digest}.bin"
        expected_names.add(name)
        try:
            info = package.getinfo(name)
        except KeyError as exc:
            raise CompressionError(f"payload ausente: {digest}") from exc
        if info.compress_type != zipfile.ZIP_STORED or info.file_size != stored_size:
            raise CompressionError(f"payload ou camada ZIP divergente: {digest}")

    actual_names = {info.filename for info in package.infolist()}
    if actual_names != expected_names:
        raise CompressionError("contêiner possui entradas ausentes ou inesperadas")
    reconstructed_size = 0
    for digest in sequence:
        if not isinstance(digest, str) or digest not in chunks:
            raise CompressionError("sequência referencia chunk inexistente")
        reconstructed_size += _require_int(
            chunks[digest].get("raw_size"), field="chunk.raw_size"
        )
    if reconstructed_size != source_size:
        raise CompressionError("sequência não recompõe o tamanho declarado")
    accounting = manifest.get("accounting")
    if accounting != _derived_accounting(manifest):
        raise CompressionError("contabilidade do manifest diverge dos chunks")


def _decoded_chunks(
    package: zipfile.ZipFile,
    manifest: Mapping[str, Any],
) -> Iterator[bytes]:
    chunks = manifest["chunks"]
    for digest in manifest["sequence"]:
        metadata = chunks[digest]
        payload = package.read(f"chunks/{digest}.bin")
        if _sha256(payload) != metadata["payload_sha256"]:
            raise CompressionError(f"hash do payload divergente: {digest}")
        try:
            decoded = decode_chunk(
                payload,
                codec=metadata["codec"],
                expected_size=metadata["raw_size"],
            )
        except CodecError as exc:
            raise CompressionError(f"não foi possível reconstruir o chunk {digest}") from exc
        if _sha256(decoded) != digest:
            raise CompressionError(f"hash do chunk reconstruído divergente: {digest}")
        yield decoded


def inspect_archive(archive: str | Path) -> dict[str, Any]:
    archive_path = Path(archive).resolve(strict=True)
    package, manifest, manifest_bytes = _load_manifest(archive_path)
    try:
        _validate_manifest(manifest, package)
        source = manifest["source"]
        accounting = _derived_accounting(manifest)
        return {
            "schema": manifest["schema"],
            "archive": str(archive_path),
            "archive_sha256": _sha256_file(archive_path),
            "archive_bytes": archive_path.stat().st_size,
            "manifest_sha256": _sha256(manifest_bytes),
            "source_name": source.get("name"),
            "source_sha256": source["sha256"],
            "source_bytes": source["size"],
            "chunk_references": len(manifest["sequence"]),
            "unique_chunks": len(manifest["chunks"]),
            "deduplicated_bytes": accounting.get("deduplicated_bytes", 0),
            "verified": False,
        }
    finally:
        package.close()


def verify_archive(archive: str | Path) -> dict[str, Any]:
    archive_path = Path(archive).resolve(strict=True)
    package, manifest, manifest_bytes = _load_manifest(archive_path)
    try:
        _validate_manifest(manifest, package)
        reconstructed_hash = hashlib.sha256()
        reconstructed_size = 0
        for decoded in _decoded_chunks(package, manifest):
            reconstructed_hash.update(decoded)
            reconstructed_size += len(decoded)
        source = manifest["source"]
        if reconstructed_size != source["size"]:
            raise CompressionError("tamanho reconstruído diverge da fonte")
        if reconstructed_hash.hexdigest() != source["sha256"]:
            raise CompressionError("SHA-256 reconstruído diverge da fonte")
        accounting = _derived_accounting(manifest)
        return {
            "schema": manifest["schema"],
            "source_name": source.get("name"),
            "source_sha256": source["sha256"],
            "source_bytes": reconstructed_size,
            "manifest_sha256": _sha256(manifest_bytes),
            "chunk_references": len(manifest["sequence"]),
            "unique_chunks": len(manifest["chunks"]),
            "deduplicated_bytes": accounting.get("deduplicated_bytes", 0),
            "verified": True,
            "silent_discards": 0,
        }
    finally:
        package.close()


def unpack_file(
    archive: str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    archive_path = Path(archive).resolve(strict=True)
    destination_path = Path(destination).resolve(strict=False)
    if destination_path.exists() and not overwrite:
        raise CompressionError(f"destino já existe: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    package, manifest, _ = _load_manifest(archive_path)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".partial",
        dir=destination_path.parent,
    )
    temporary_path = Path(temporary_name)
    restored_hash = hashlib.sha256()
    restored_size = 0
    try:
        _validate_manifest(manifest, package)
        with os.fdopen(fd, "wb") as output:
            fd = -1
            for decoded in _decoded_chunks(package, manifest):
                output.write(decoded)
                restored_hash.update(decoded)
                restored_size += len(decoded)
            output.flush()
            os.fsync(output.fileno())
        source = manifest["source"]
        if restored_size != source["size"] or restored_hash.hexdigest() != source["sha256"]:
            raise CompressionError("restauração não preservou a fonte")
        os.replace(temporary_path, destination_path)
        return {
            "archive": str(archive_path),
            "destination": str(destination_path),
            "restored_bytes": restored_size,
            "restored_sha256": restored_hash.hexdigest(),
            "verified": True,
            "silent_discards": 0,
        }
    except Exception:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        package.close()
