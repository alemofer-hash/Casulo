from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .domain import CreationAggregate, CreationSpec, CreationState, canonical_json
from .platform_contracts import PlatformError
from .simulation import SimulationReceipt
from .t_forge import ForgeReceipt


_SECRET_KEY = re.compile(r"(?:secret|password|passwd|api[_-]?key|private[_-]?key|access[_-]?token|refresh[_-]?token)", re.I)
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


class MaterializationError(PlatformError):
    pass


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    package_id: str
    directory: Path
    archive: Path
    archive_sha256: str
    manifest_sha256: str
    files: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.materialization-receipt/1.0",
            "package_id": self.package_id,
            "directory": str(self.directory),
            "archive": str(self.archive),
            "archive_sha256": self.archive_sha256,
            "manifest_sha256": self.manifest_sha256,
            "files": dict(self.files),
        }


@dataclass(frozen=True, slots=True)
class TargetCompatibility:
    target: str
    supported: bool
    entrypoint: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "supported": self.supported,
            "entrypoint": self.entrypoint,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ExecutableAgentBundle:
    """Engine-neutral, already compiled T payload accepted by the exporter."""

    artifact_id: str
    operation: str
    executable: bytes
    artifact_manifest: Mapping[str, Any]
    tcap: bytes
    project_manifest: Mapping[str, Any]
    source_t: bytes | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id.startswith("sha256:") or not self.operation.strip():
            raise MaterializationError("bundle executavel exige identidade e operacao")
        if not self.executable or len(self.executable) > 8 * 1024 * 1024:
            raise MaterializationError("executavel T ausente ou excessivo")
        if not self.tcap or len(self.tcap) > 32 * 1024 * 1024:
            raise MaterializationError("TCAP ausente ou excessivo")
        if self.source_t is not None and (not self.source_t or len(self.source_t) > 2 * 1024 * 1024):
            raise MaterializationError("source T vazio ou excessivo")
        canonical_json(dict(self.artifact_manifest))
        canonical_json(dict(self.project_manifest))

    def payloads(self) -> dict[str, bytes]:
        descriptor = {
            "schema": "casulo.materialized-t-agent/1.0",
            "artifact_id": self.artifact_id,
            "operation": self.operation,
            "executable_file": "agent.py",
            "tcap_file": "agent.tcap",
            "real_effects_included": False,
        }
        payloads = {
            "agent.py": bytes(self.executable),
            "agent.tcap": bytes(self.tcap),
            "agent-descriptor.json": canonical_json(descriptor),
            "agent-artifact-manifest.json": canonical_json(dict(self.artifact_manifest)),
            "agent-project.json": canonical_json(dict(self.project_manifest)),
        }
        if self.source_t is not None:
            payloads["source.t"] = bytes(self.source_t)
        return payloads


@dataclass(frozen=True, slots=True)
class ImportedMaterialization:
    archive: Path
    archive_sha256: str
    package_id: str
    creation: CreationSpec
    manifest_sha256: str
    agent_artifact_id: str | None = None
    agent_operation: str | None = None

    def aggregate_for_reedit(self) -> CreationAggregate:
        return CreationAggregate(self.creation)


class Materializer:
    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root).expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)

    def materialize(
        self,
        creation: CreationSpec,
        *,
        forge_receipt: ForgeReceipt,
        simulation_receipt: SimulationReceipt,
        executable_bundle: ExecutableAgentBundle | None = None,
        signature_class: str = "UNSIGNED_LOCAL_DEVELOPMENT",
    ) -> MaterializationReceipt:
        self._preflight(creation, simulation_receipt)
        package_id = f"creation-{hashlib.sha256(creation.creation_id.encode()).hexdigest()[:16]}-v{creation.version}"
        destination = (self.output_root / package_id).resolve()
        archive = (self.output_root / f"{package_id}.casulo.zip").resolve()
        self._confined(destination)
        self._confined(archive)
        if destination.exists() or archive.exists():
            raise MaterializationError("pacote já existe; overwrite é negado")
        staging = (self.output_root / f".{package_id}.{os.getpid()}.staging").resolve()
        self._confined(staging)
        if staging.exists():
            raise MaterializationError("staging já existe")
        staging.mkdir()
        try:
            payloads = {
                "creation.json": canonical_json(creation.to_dict()),
                "forge-receipt.json": canonical_json(forge_receipt.to_dict()),
                "simulation-receipt.json": canonical_json(simulation_receipt.to_dict()),
                "api.py": _api_source().encode("utf-8"),
                "index.html": _desktop_source().encode("utf-8"),
            }
            if executable_bundle is not None:
                _reject_secrets(dict(executable_bundle.project_manifest))
                payloads.update(executable_bundle.payloads())
            sbom = _sbom(package_id, payloads)
            payloads["SBOM.spdx.json"] = canonical_json(sbom)
            for relative, payload in payloads.items():
                (staging / relative).write_bytes(payload)
            payload_hashes = {name: _sha256_bytes(payload) for name, payload in payloads.items()}
            manifest = {
                "schema": "casulo.materialized-package/1.0",
                "package_id": package_id,
                "creation_id": creation.creation_id,
                "creation_version": creation.version,
                "profile": (
                    "hosted-local-api+compiled-t-agent"
                    if executable_bundle is not None
                    else "hosted-local-api"
                ),
                "engine_boundary": "engine-agnostic-no-owner-components",
                "bind_policy": "127.0.0.1-only",
                "real_effects_included": False,
                "spec_hash": creation.sha256,
                "T_source_hashes": [artifact.source_sha256 for artifact in forge_receipt.artifacts],
                "IR_hashes": [artifact.ir_sha256 for artifact in forge_receipt.artifacts],
                "graph_hashes": [artifact.graph_sha256 for artifact in forge_receipt.artifacts],
                "TCAP_hash": None if executable_bundle is None else _sha256_bytes(executable_bundle.tcap),
                "compiler_abi": "casulo-artifact/0.8",
                "targets": [target.to_dict() for target in _target_compatibility(executable_bundle)],
                "capabilities": sorted(creation.capabilities),
                "resource_limits": {"request_body_bytes": 1024, "archive_bytes": 32 * 1024 * 1024, "network": "loopback-only"},
                "runtime_dependencies": ["Python >=3.11 stdlib"],
                "model_requirements": [],
                "secret_slots": [],
                "provenance_root": simulation_receipt.head_hash,
                "signature_class": signature_class,
                "import_compatibility": "casulo.materialized-package/1.x",
                "update_channel": "offline-development",
                "files": payload_hashes,
            }
            if executable_bundle is not None:
                manifest["executable_agent"] = {
                    "artifact_id": executable_bundle.artifact_id,
                    "operation": executable_bundle.operation,
                    "file": "agent.py",
                    "tcap_file": "agent.tcap",
                }
            manifest_bytes = canonical_json(manifest)
            (staging / "MANIFEST.json").write_bytes(manifest_bytes)
            all_hashes = {**payload_hashes, "MANIFEST.json": _sha256_bytes(manifest_bytes)}
            sums = "".join(f"{digest}  {name}\n" for name, digest in sorted(all_hashes.items()))
            (staging / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
            os.replace(staging, destination)
            _reproducible_zip(destination, archive)
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        final_hashes = tuple(
            (path.name, _sha256_file(path))
            for path in sorted(destination.iterdir(), key=lambda item: item.name)
            if path.is_file()
        )
        return MaterializationReceipt(
            package_id,
            destination,
            archive,
            _sha256_file(archive),
            _sha256_file(destination / "MANIFEST.json"),
            final_hashes,
        )

    def _preflight(self, creation: CreationSpec, simulation: SimulationReceipt) -> None:
        if creation.state is not CreationState.AGREEMENT:
            raise MaterializationError("materialização exige estado AGREEMENT")
        if simulation.creation_id != creation.creation_id or simulation.status != "PASS":
            raise MaterializationError("simulação PASS correspondente é obrigatória")
        if simulation.real_effects_executed:
            raise MaterializationError("receipt com efeito real é inelegível")
        _reject_secrets(creation.to_dict())

    def _confined(self, path: Path) -> None:
        try:
            path.relative_to(self.output_root)
        except ValueError as error:
            raise MaterializationError("destino escapou da raiz de exportação") from error


class MaterializedPackageImporter:
    """Fail-closed, non-executing import of a materialized Casulo archive."""

    MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
    MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

    def import_archive(self, archive: str | Path) -> ImportedMaterialization:
        source = Path(archive).expanduser().resolve(strict=True)
        if not source.is_file() or source.is_symlink():
            raise MaterializationError("import exige arquivo regular")
        if source.stat().st_size > self.MAX_ARCHIVE_BYTES:
            raise MaterializationError("arquivo Casulo excede limite")
        try:
            with zipfile.ZipFile(source) as package:
                infos = package.infolist()
                names = [info.filename for info in infos]
                if len(names) != len(set(names)):
                    raise MaterializationError("ZIP contem nomes duplicados")
                if any(
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or "\\" in info.filename
                    or Path(info.filename).is_absolute()
                    or len(Path(info.filename).parts) != 1
                    or info.filename in {".", ".."}
                    for info in infos
                ):
                    raise MaterializationError("layout ZIP inseguro")
                if sum(info.file_size for info in infos) > self.MAX_UNCOMPRESSED_BYTES:
                    raise MaterializationError("conteudo Casulo descompactado excede limite")
                legacy_base = {
                    "creation.json",
                    "forge-receipt.json",
                    "simulation-receipt.json",
                    "api.py",
                    "SBOM.spdx.json",
                    "MANIFEST.json",
                    "SHA256SUMS",
                }
                current_base = legacy_base | {"index.html"}
                agent_required = {
                    "agent.py",
                    "agent.tcap",
                    "agent-descriptor.json",
                    "agent-artifact-manifest.json",
                    "agent-project.json",
                }
                required = frozenset(names)
                accepted = {
                    frozenset(legacy_base),
                    frozenset(legacy_base | agent_required),
                    frozenset(current_base),
                    frozenset(current_base | agent_required),
                    frozenset(current_base | agent_required | {"source.t"}),
                }
                if required not in accepted:
                    raise MaterializationError("conteudo do pacote diverge do contrato")
                payloads = {name: package.read(name) for name in names}
        except MaterializationError:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise MaterializationError(f"arquivo Casulo invalido: {type(error).__name__}") from error

        try:
            manifest = json.loads(payloads["MANIFEST.json"].decode("utf-8"))
            creation_payload = json.loads(payloads["creation.json"].decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise MaterializationError("JSON canonico invalido no pacote") from error
        if manifest.get("schema") != "casulo.materialized-package/1.0":
            raise MaterializationError("schema do pacote nao suportado")
        if manifest.get("engine_boundary") != "engine-agnostic-no-owner-components":
            raise MaterializationError("fronteira de engine invalida")
        if manifest.get("real_effects_included") is not False:
            raise MaterializationError("pacote importado nao pode conter efeitos reais")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != required - {"MANIFEST.json", "SHA256SUMS"}:
            raise MaterializationError("manifesto de arquivos invalido")
        for name, expected in files.items():
            if expected != _sha256_bytes(payloads[name]):
                raise MaterializationError(f"hash divergente: {name}")
        sums = _parse_sums(payloads["SHA256SUMS"])
        if set(sums) != required - {"SHA256SUMS"}:
            raise MaterializationError("SHA256SUMS incompleto")
        for name, expected in sums.items():
            if expected != _sha256_bytes(payloads[name]):
                raise MaterializationError(f"SHA256SUMS divergente: {name}")
        creation = _creation_from_payload(creation_payload)
        if creation.creation_id != manifest.get("creation_id") or creation.version != manifest.get("creation_version"):
            raise MaterializationError("identidade/versao diverge do manifesto")
        _reject_secrets(creation.to_dict())
        executable = manifest.get("executable_agent")
        if executable is not None:
            if (
                not isinstance(executable, dict)
                or set(executable) != {"artifact_id", "operation", "file", "tcap_file"}
                or executable.get("file") != "agent.py"
                or executable.get("tcap_file") != "agent.tcap"
                or not str(executable.get("artifact_id", "")).startswith("sha256:")
                or not str(executable.get("operation", "")).strip()
            ):
                raise MaterializationError("descritor do agente executavel invalido")
        return ImportedMaterialization(
            source,
            _sha256_file(source),
            str(manifest.get("package_id")),
            creation,
            _sha256_bytes(payloads["MANIFEST.json"]),
            None if executable is None else str(executable["artifact_id"]),
            None if executable is None else str(executable["operation"]),
        )


def _reject_secrets(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                raise MaterializationError(f"campo secreto negado: {'.'.join((*path, str(key)))}")
            _reject_secrets(item, (*path, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secrets(item, (*path, str(index)))
    elif isinstance(value, str) and _PEM.search(value):
        raise MaterializationError("material de chave privada negado")


def _sbom(package_id: str, payloads: Mapping[str, bytes]) -> dict[str, Any]:
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": package_id,
        "documentNamespace": f"https://teloscorp.invalid/spdx/{package_id}",
        "creationInfo": {"creators": ["Organization: Teloscorp"], "created": "1980-01-01T00:00:00Z"},
        "files": [
            {
                "fileName": name,
                "SPDXID": f"SPDXRef-File-{index}",
                "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256_bytes(payload)}],
            }
            for index, (name, payload) in enumerate(sorted(payloads.items()), start=1)
        ],
        "packages": [
            {
                "name": "python-stdlib",
                "SPDXID": "SPDXRef-Package-PythonStdlib",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "PSF-2.0",
            }
        ],
    }


def _target_compatibility(bundle: ExecutableAgentBundle | None) -> tuple[TargetCompatibility, ...]:
    has_agent = bundle is not None
    return (
        TargetCompatibility("casulo-package", True, "MANIFEST.json", "import/re-edit contract included"),
        TargetCompatibility("cli", has_agent, "agent.py" if has_agent else None, "compiled T entrypoint" if has_agent else "creation has no executable T bundle"),
        TargetCompatibility("api-loopback", True, "api.py", "typed bounded simulation API"),
        TargetCompatibility("local-service", True, "api.py", "loopback lifecycle with bounded requests"),
        TargetCompatibility("desktop-web-local", True, "index.html", "self-contained accessible UI served by the local service"),
    )


def _api_source() -> str:
    return '''from __future__ import annotations
import argparse, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CREATION = json.loads((ROOT / "creation.json").read_text(encoding="utf-8"))
SIMULATION = json.loads((ROOT / "simulation-receipt.json").read_text(encoding="utf-8"))

class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload, content_type="application/json; charset=utf-8"):
        if isinstance(payload, str): body = payload.encode("utf-8")
        else: body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'none'; connect-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/": self._send(200, (ROOT / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
        elif self.path == "/health": self._send(200, {"ok": True, "effects": "simulation-only"})
        elif self.path == "/creation": self._send(200, CREATION)
        else: self._send(404, {"error": "not_found"})
    def do_POST(self):
        if self.path != "/simulate": self._send(404, {"error": "not_found"}); return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024: self._send(413, {"error": "body_too_large"}); return
        if length: self.rfile.read(length)
        self._send(200, SIMULATION)
    def log_message(self, *_args): return

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--port", type=int, default=8765); parser.add_argument("--once", action="store_true")
    args = parser.parse_args(); server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"bind": "127.0.0.1", "port": server.server_port}), flush=True)
    server.handle_request() if args.once else server.serve_forever()

if __name__ == "__main__": main()
'''


def _desktop_source() -> str:
    return '''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Casulo materializado</title><style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#071018;color:#e9f0ef}body{margin:0;min-height:100vh;display:grid;place-items:center}
main{width:min(42rem,calc(100% - 3rem));padding:2rem;border:1px solid #29404c;border-radius:1.4rem;background:#0c1821}
.form{width:5rem;height:5rem;border-radius:50%;background:radial-gradient(circle at 35% 30%,#e9ad61,#234d69 58%,#071018);box-shadow:0 0 4rem #1c5474;margin-bottom:1.5rem}
h1{font-size:clamp(1.6rem,5vw,2.8rem);margin:.25rem 0}.state{color:#e9ad61}p{line-height:1.65;color:#b9c9cd}</style></head>
<body><main aria-labelledby="title"><div class="form" aria-hidden="true"></div><p class="state">MATERIALIZADO · SIMULAÇÃO</p>
<h1 id="title">Criação Casulo</h1><p>Este pacote executa localmente, com efeitos reais desabilitados e API confinada ao loopback.</p></main></body></html>'''


def _reproducible_zip(directory: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_sums(payload: bytes) -> dict[str, str]:
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise MaterializationError("SHA256SUMS precisa ser ASCII") from error
    result: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or any(char not in "0123456789abcdef" for char in parts[0]):
            raise MaterializationError("linha SHA256SUMS invalida")
        digest, name = parts
        if not name or name in result:
            raise MaterializationError("nome duplicado em SHA256SUMS")
        result[name] = digest
    return result


def _creation_from_payload(payload: Any) -> CreationSpec:
    if not isinstance(payload, dict) or payload.get("schema") != "casulo.creation/1.0":
        raise MaterializationError("CreationSpec importada invalida")
    try:
        return CreationSpec(
            creation_id=payload["creation_id"],
            version=payload["version"],
            state=CreationState(payload["state"]),
            content=payload["content"],
            capabilities=frozenset(payload["capabilities"]),
            rejected_delta_ids=tuple(payload["rejected_delta_ids"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MaterializationError("campos CreationSpec importados invalidos") from error
