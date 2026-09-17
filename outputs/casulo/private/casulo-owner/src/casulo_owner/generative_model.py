from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable


CANDIDATE_SCHEMA = "casulo-generative-candidate/1.0"
ADOPTION_SCHEMA = "casulo-generative-adoption/1.0"
MINIMUM_RESERVE_BYTES = 20 * 1024**3
MAX_CANDIDATE_BYTES = 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ALLOWED_DOWNLOAD_HOSTS = frozenset({"github.com", "huggingface.co"})
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class GenerativeModelError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadAsset:
    kind: str
    name: str
    url: str
    bytes: int
    sha256: str
    license_id: str

    @classmethod
    def from_dict(cls, kind: str, value: Any) -> "DownloadAsset":
        if not isinstance(value, dict):
            raise GenerativeModelError(f"asset {kind} inválido")
        name_key = "file" if kind == "model" else "asset"
        required = {name_key, "url", "bytes", "sha256", "license"}
        if not required <= value.keys():
            raise GenerativeModelError(f"asset {kind} incompleto")
        name = str(value[name_key])
        if Path(name).name != name or not name:
            raise GenerativeModelError(f"nome inseguro no asset {kind}")
        url = str(value["url"])
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
            raise GenerativeModelError(f"origem não autorizada no asset {kind}")
        size = value["bytes"]
        digest = str(value["sha256"])
        if not isinstance(size, int) or not 0 < size <= 12 * 1024**3:
            raise GenerativeModelError(f"tamanho inválido no asset {kind}")
        if not _SHA256.fullmatch(digest):
            raise GenerativeModelError(f"SHA-256 inválido no asset {kind}")
        return cls(kind, name, url, size, digest, str(value["license"]))


@dataclass(frozen=True, slots=True)
class GenerativeCandidate:
    candidate_id: str
    manifest_path: Path
    manifest_sha256: str
    model: DownloadAsset
    runtime: DownloadAsset
    runtime_required_executable: str
    runtime_max_unpacked_bytes: int
    minimum_reserve_bytes: int
    projected_adoption_peak_bytes: int
    payload: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "GenerativeCandidate":
        manifest = Path(path).expanduser().resolve(strict=True)
        if manifest.is_symlink() or not manifest.is_file():
            raise GenerativeModelError("manifesto generativo precisa ser arquivo regular")
        raw = manifest.read_bytes()
        if len(raw) > MAX_CANDIDATE_BYTES:
            raise GenerativeModelError("manifesto generativo grande demais")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GenerativeModelError("manifesto generativo inválido") from error
        if not isinstance(payload, dict) or payload.get("schema") != CANDIDATE_SCHEMA:
            raise GenerativeModelError("schema do candidato generativo inválido")
        candidate_id = str(payload.get("candidate_id", ""))
        if not _SAFE_ID.fullmatch(candidate_id):
            raise GenerativeModelError("candidate_id inseguro")
        model = DownloadAsset.from_dict("model", payload.get("model"))
        runtime_raw = payload.get("runtime")
        runtime = DownloadAsset.from_dict("runtime", runtime_raw)
        assert isinstance(runtime_raw, dict)
        required_executable = str(runtime_raw.get("required_executable", ""))
        if Path(required_executable).name != required_executable or not required_executable:
            raise GenerativeModelError("executável requerido do runtime é inseguro")
        unpacked = runtime_raw.get("max_unpacked_bytes")
        storage = payload.get("storage")
        if not isinstance(unpacked, int) or not runtime.bytes <= unpacked <= 2 * 1024**3:
            raise GenerativeModelError("limite de extração do runtime inválido")
        if not isinstance(storage, dict):
            raise GenerativeModelError("contrato de armazenamento ausente")
        reserve = storage.get("minimum_reserve_bytes")
        peak = storage.get("projected_adoption_peak_bytes")
        if not isinstance(reserve, int) or reserve < MINIMUM_RESERVE_BYTES:
            raise GenerativeModelError("reserva operacional abaixo de 20 GiB")
        minimum_peak = 2 * (model.bytes + runtime.bytes) + unpacked
        if not isinstance(peak, int) or peak < minimum_peak:
            raise GenerativeModelError("pico projetado não cobre staging e adoção")
        if payload.get("network_required_after_install") is not False:
            raise GenerativeModelError("candidato exige rede depois da instalação")
        if payload.get("commercial_ai_api_required") is not False:
            raise GenerativeModelError("API comercial é proibida")
        if payload.get("training_with_user_content") is not False:
            raise GenerativeModelError("treino com conteúdo do usuário é proibido")
        return cls(
            candidate_id,
            manifest,
            hashlib.sha256(raw).hexdigest(),
            model,
            runtime,
            required_executable,
            unpacked,
            reserve,
            peak,
            payload,
        )

    @property
    def consent_phrase(self) -> str:
        total = self.model.bytes + self.runtime.bytes
        return f"AUTORIZO ADOTAR {self.candidate_id} BAIXANDO {total} BYTES VERIFICADOS"


def adoption_plan(candidate: GenerativeCandidate, cache_root: str | Path) -> dict[str, Any]:
    root = Path(cache_root).expanduser().resolve(strict=False)
    existing = _existing_ancestor(root)
    free = shutil.disk_usage(existing).free
    return {
        "schema": "casulo-generative-adoption-plan/1.0",
        "candidate_id": candidate.candidate_id,
        "manifest_sha256": candidate.manifest_sha256,
        "cache_root": str(root),
        "model": _asset_report(candidate.model),
        "runtime": _asset_report(candidate.runtime),
        "download_bytes": candidate.model.bytes + candidate.runtime.bytes,
        "projected_peak_bytes": candidate.projected_adoption_peak_bytes,
        "free_bytes_before": free,
        "projected_free_bytes_after_peak": free - candidate.projected_adoption_peak_bytes,
        "minimum_reserve_bytes": candidate.minimum_reserve_bytes,
        "storage_gate": free - candidate.projected_adoption_peak_bytes >= candidate.minimum_reserve_bytes,
        "consent_phrase": candidate.consent_phrase,
        "mutations_performed": False,
        "network_access_performed": False,
    }


def adoption_doctor(candidate: GenerativeCandidate, cache_root: str | Path) -> dict[str, Any]:
    root = Path(cache_root).expanduser().resolve(strict=False)
    target = root / candidate.candidate_id
    receipt_path = target / "ADOPTION.json"
    report: dict[str, Any] = {
        "schema": "casulo-generative-doctor/1.0",
        "candidate_id": candidate.candidate_id,
        "manifest_sha256": candidate.manifest_sha256,
        "cache_root": str(root),
        "target": str(target),
        "network_access_performed": False,
        "mutations_performed": False,
        "ready": False,
        "status": "MISSING",
        "reasons": [],
    }
    if not receipt_path.is_file() or receipt_path.is_symlink():
        report["reasons"].append("receipt de adoção ausente")
        return report
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        report["status"] = "INVALID"
        report["reasons"].append(f"receipt inválido: {type(error).__name__}")
        return report
    if not isinstance(receipt, dict) or receipt.get("schema") != ADOPTION_SCHEMA:
        report["status"] = "INVALID"
        report["reasons"].append("schema de receipt inválido")
        return report
    expected_identity = {
        "candidate_id": candidate.candidate_id,
        "candidate_manifest_sha256": candidate.manifest_sha256,
        "model_sha256": candidate.model.sha256,
        "runtime_archive_sha256": candidate.runtime.sha256,
    }
    for key, value in expected_identity.items():
        if receipt.get(key) != value:
            report["reasons"].append(f"identidade divergente: {key}")
    model_path = _confined_receipt_path(target, receipt.get("model_file"), report)
    runtime_executable = _confined_receipt_path(target, receipt.get("runtime_executable"), report)
    if model_path is not None and not _matches_asset(model_path, candidate.model):
        report["reasons"].append("peso local diverge em tamanho ou hash")
    if runtime_executable is not None:
        if runtime_executable.name != candidate.runtime_required_executable or not runtime_executable.is_file():
            report["reasons"].append("executável do runtime ausente")
    runtime_files = receipt.get("runtime_files")
    if not isinstance(runtime_files, list) or not runtime_files:
        report["reasons"].append("manifesto de arquivos do runtime ausente")
    else:
        for item in runtime_files:
            if not isinstance(item, dict):
                report["reasons"].append("entrada de runtime inválida")
                continue
            path = _confined_receipt_path(target, item.get("path"), report)
            digest = item.get("sha256")
            size = item.get("bytes")
            if path is None or not _SHA256.fullmatch(str(digest)) or not isinstance(size, int):
                report["reasons"].append("metadado de runtime inválido")
            elif not path.is_file() or path.stat().st_size != size or _sha256(path) != digest:
                report["reasons"].append(f"arquivo de runtime diverge: {item.get('path')}")
    report["ready"] = not report["reasons"]
    report["status"] = "READY" if report["ready"] else "INVALID"
    if report["ready"]:
        report["model_file"] = str(model_path)
        report["runtime_executable"] = str(runtime_executable)
        report["adoption_receipt_sha256"] = _sha256(receipt_path)
    return report


Fetcher = Callable[[str, Path, int], None]


def adopt_candidate(
    candidate: GenerativeCandidate,
    cache_root: str | Path,
    *,
    consent: str,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    if consent != candidate.consent_phrase:
        raise GenerativeModelError("consentimento literal divergente; nenhuma adoção iniciada")
    plan = adoption_plan(candidate, cache_root)
    if not plan["storage_gate"]:
        raise GenerativeModelError("adoção violaria a reserva operacional de 20 GiB")
    root = Path(cache_root).expanduser().resolve(strict=False)
    _reject_symlink_ancestors(root)
    prior = adoption_doctor(candidate, root)
    if prior["ready"]:
        return prior
    target = root / candidate.candidate_id
    if target.exists():
        raise GenerativeModelError("cache existente não verificado; overwrite negado")
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{candidate.candidate_id}-{uuid.uuid4().hex}"
    staging.mkdir()
    actual_fetcher = fetcher or _download
    try:
        model_dir = staging / "model"
        runtime_dir = staging / "runtime"
        model_dir.mkdir()
        runtime_dir.mkdir()
        model_path = model_dir / candidate.model.name
        runtime_archive = staging / candidate.runtime.name
        actual_fetcher(candidate.model.url, model_path, candidate.model.bytes)
        _require_asset(model_path, candidate.model)
        actual_fetcher(candidate.runtime.url, runtime_archive, candidate.runtime.bytes)
        _require_asset(runtime_archive, candidate.runtime)
        _safe_extract_runtime(runtime_archive, runtime_dir, candidate.runtime_max_unpacked_bytes)
        executables = tuple(runtime_dir.rglob(candidate.runtime_required_executable))
        if len(executables) != 1 or executables[0].is_symlink():
            raise GenerativeModelError("runtime precisa conter exatamente um llama-server verificado")
        runtime_files = tuple(sorted(path for path in runtime_dir.rglob("*") if path.is_file()))
        runtime_manifest = [
            {
                "path": path.relative_to(staging).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in runtime_files
        ]
        receipt = {
            "schema": ADOPTION_SCHEMA,
            "candidate_id": candidate.candidate_id,
            "candidate_manifest_sha256": candidate.manifest_sha256,
            "adopted_at": datetime.now(UTC).isoformat(),
            "model_file": model_path.relative_to(staging).as_posix(),
            "model_bytes": candidate.model.bytes,
            "model_sha256": candidate.model.sha256,
            "model_license": candidate.model.license_id,
            "runtime_archive_sha256": candidate.runtime.sha256,
            "runtime_license": candidate.runtime.license_id,
            "runtime_executable": executables[0].relative_to(staging).as_posix(),
            "runtime_files": runtime_manifest,
            "network_required_after_install": False,
            "commercial_ai_api_used": False,
            "training_with_user_content": False,
            "explicit_consent_sha256": hashlib.sha256(consent.encode("utf-8")).hexdigest(),
        }
        runtime_archive.unlink()
        receipt_path = staging / "ADOPTION.json"
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        staging.replace(target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    verified = adoption_doctor(candidate, root)
    if not verified["ready"]:
        raise GenerativeModelError("adoção terminou sem verificação integral")
    return verified


def _asset_report(asset: DownloadAsset) -> dict[str, Any]:
    return {
        "name": asset.name,
        "url": asset.url,
        "bytes": asset.bytes,
        "sha256": asset.sha256,
        "license": asset.license_id,
    }


def _download(url: str, destination: Path, expected_bytes: int) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Casulo-owner-adoption/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("xb") as output:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != expected_bytes:
            raise GenerativeModelError("Content-Length diverge do manifesto")
        observed = 0
        while True:
            chunk = response.read(min(1024 * 1024, expected_bytes - observed + 1))
            if not chunk:
                break
            observed += len(chunk)
            if observed > expected_bytes:
                raise GenerativeModelError("download excedeu o tamanho selado")
            output.write(chunk)
    if observed != expected_bytes:
        raise GenerativeModelError("download truncado")


def _safe_extract_runtime(archive: Path, destination: Path, max_unpacked_bytes: int) -> None:
    with zipfile.ZipFile(archive) as handle:
        entries = handle.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise GenerativeModelError("runtime archive possui entradas demais")
        total = 0
        for entry in entries:
            pure = PurePosixPath(entry.filename.replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                raise GenerativeModelError("path traversal no runtime archive")
            _validate_safe_parts(pure.parts, source="runtime archive")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise GenerativeModelError("symlink no runtime archive")
            total += entry.file_size
            if total > max_unpacked_bytes:
                raise GenerativeModelError("runtime archive excede limite descompactado")
            output = (destination / Path(*pure.parts)).resolve()
            try:
                output.relative_to(destination.resolve())
            except ValueError as error:
                raise GenerativeModelError("runtime archive escapou do staging") from error
            if entry.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(entry) as source, output.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _reject_symlink_ancestors(path: Path) -> None:
    existing = _existing_ancestor(path)
    current = existing
    while True:
        if current.is_symlink():
            raise GenerativeModelError("cache não pode atravessar symlink")
        if current == current.parent:
            break
        current = current.parent


def _confined_receipt_path(target: Path, relative: Any, report: dict[str, Any]) -> Path | None:
    if not isinstance(relative, str) or not relative:
        report["reasons"].append("path ausente no receipt")
        return None
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        report["reasons"].append("path inseguro no receipt")
        return None
    try:
        _validate_safe_parts(pure.parts, source="receipt")
    except GenerativeModelError as error:
        report["reasons"].append(str(error))
        return None
    cursor = target
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            report["reasons"].append("symlink negado no cache")
            return None
    path = (target / Path(*pure.parts)).resolve()
    try:
        path.relative_to(target.resolve())
    except ValueError:
        report["reasons"].append("path escapou do cache")
        return None
    if path.is_symlink():
        report["reasons"].append("symlink negado no cache")
        return None
    return path


def _matches_asset(path: Path, asset: DownloadAsset) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size == asset.bytes and _sha256(path) == asset.sha256


def _require_asset(path: Path, asset: DownloadAsset) -> None:
    if not _matches_asset(path, asset):
        raise GenerativeModelError(f"asset {asset.kind} diverge em tamanho ou SHA-256")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_safe_parts(parts: tuple[str, ...], *, source: str) -> None:
    for part in parts:
        if not part or part in {".", ".."} or part.endswith((" ", ".")) or ":" in part:
            raise GenerativeModelError(f"componente inseguro em {source}")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_DEVICE_NAMES:
            raise GenerativeModelError(f"device name negado em {source}")
