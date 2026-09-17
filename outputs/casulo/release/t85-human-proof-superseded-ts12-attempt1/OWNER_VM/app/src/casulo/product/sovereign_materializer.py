from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from casulo.t.v2_tcap import verify_tcap_v2

from .domain import CreationAggregate, CreationSpec, CreationState, canonical_json
from .materializer import MaterializationError
from .simulation import SimulationReceipt
from .t_forge import ForgeReceipt


SCHEMA_V2 = "casulo.materialized-package/2.0"
SIGNATURE_CLASS = "DEVELOPMENT_NOT_COMMERCIAL"
_SECRET = re.compile(r"(?:secret|password|passwd|api[_-]?key|private[_-]?key|access[_-]?token|refresh[_-]?token)", re.I)
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_SAFE_PART = re.compile(r"[A-Za-z0-9_.-]{1,128}")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_secrets(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _SECRET.search(str(key)):
                raise MaterializationError(f"secret field denied: {key}")
            _reject_secrets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secrets(item)
    elif isinstance(value, str) and _PEM.search(value):
        raise MaterializationError("private key material denied")


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name or "\\" in name or path.is_absolute() or path.parts[0] in {".", ".."}
        or any(part in {"", ".", ".."} or not _SAFE_PART.fullmatch(part) or ":" in part for part in path.parts)
    ):
        raise MaterializationError("unsafe package path")
    return path


@dataclass(frozen=True, slots=True)
class SovereignTAgentBundle:
    tcap_root: Path
    runtime_executable: Path
    entry_module: str
    entry_function: str
    agent_id: str
    project_manifest: Mapping[str, Any]

    def __post_init__(self) -> None:
        root, _manifest, typed = verify_tcap_v2(self.tcap_root)
        runtime = self.runtime_executable.resolve(strict=True)
        if runtime.is_symlink() or not runtime.is_file():
            raise MaterializationError("T runtime must be a regular file")
        modules = {item["module"]: item for item in typed["modules"]}
        if self.entry_module not in modules or self.entry_function not in {item["name"] for item in modules[self.entry_module]["functions"]}:
            raise MaterializationError("T entrypoint absent from TCAP v2")
        if not self.agent_id or not self.agent_id.startswith("owner.agent."):
            raise MaterializationError("nontrivial owner T agent id required")
        if root != self.tcap_root.resolve():
            raise MaterializationError("TCAP root resolution diverged")
        _reject_secrets(dict(self.project_manifest))

    def payloads(self) -> dict[str, bytes]:
        root, manifest, typed = verify_tcap_v2(self.tcap_root)
        payloads: dict[str, bytes] = {
            "agent.py": _agent_launcher().encode("utf-8"),
            "t-runtime.exe": self.runtime_executable.read_bytes(),
            "agent-descriptor.json": canonical_json({
                "schema": "casulo.sovereign-t-agent/2.0",
                "agent_id": self.agent_id,
                "entry_module": self.entry_module,
                "entry_function": self.entry_function,
                "runtime": "t-runtime.exe",
                "tcap_root": "tcap",
                "tcap_hash": manifest["tcap_hash"],
                "module_count": len(typed["modules"]),
                "function_count": sum(len(item["functions"]) for item in typed["modules"]),
                "emit_literal": False,
            }),
            "agent-project.json": canonical_json(dict(self.project_manifest)),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.is_symlink():
                raise MaterializationError("symlink in TCAP denied")
            relative = path.relative_to(root).as_posix()
            _safe_relative(relative)
            payloads[f"tcap/{relative}"] = path.read_bytes()
        return payloads


@dataclass(frozen=True, slots=True)
class SovereignMaterializationReceipt:
    package_id: str
    directory: Path
    archive: Path
    archive_sha256: str
    manifest_sha256: str
    t_decision_receipt_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportedSovereignPackage:
    archive: Path
    archive_sha256: str
    creation: CreationSpec
    manifest: Mapping[str, Any]
    payloads: Mapping[str, bytes]

    def aggregate_for_reedit(self) -> CreationAggregate:
        return CreationAggregate(self.creation)

    def extract_to(self, destination: Path) -> Path:
        target = destination.resolve()
        if target.exists():
            raise MaterializationError("clean extraction target already exists")
        target.mkdir(parents=True)
        try:
            for name, payload in self.payloads.items():
                relative = _safe_relative(name)
                path = target.joinpath(*relative.parts).resolve()
                if not path.is_relative_to(target):
                    raise MaterializationError("extraction path escaped target")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            runtime = target / "t-runtime.exe"
            runtime.chmod(runtime.stat().st_mode | stat.S_IXUSR)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return target


class SovereignPackageImporter:
    MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
    MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024

    def import_archive(self, archive: Path) -> ImportedSovereignPackage:
        source = archive.resolve(strict=True)
        if source.is_symlink() or source.stat().st_size > self.MAX_ARCHIVE_BYTES:
            raise MaterializationError("invalid sovereign archive")
        with zipfile.ZipFile(source) as package:
            infos = package.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)) or any(item.is_dir() or item.flag_bits & 1 for item in infos):
                raise MaterializationError("duplicate, directory or encrypted ZIP entry denied")
            for name in names:
                _safe_relative(name)
            if sum(item.file_size for item in infos) > self.MAX_UNCOMPRESSED_BYTES:
                raise MaterializationError("sovereign archive expands beyond limit")
            payloads = {name: package.read(name) for name in names}
        try:
            manifest = json.loads(payloads["MANIFEST.json"])
            creation_payload = json.loads(payloads["creation.json"])
            sums = payloads["SHA256SUMS"].decode("ascii").splitlines()
        except (KeyError, UnicodeError, json.JSONDecodeError) as error:
            raise MaterializationError("sovereign package metadata invalid") from error
        if manifest.get("schema") != SCHEMA_V2 or manifest.get("engine_boundary") != "portable-t-runtime-no-owner-engine":
            raise MaterializationError("sovereign package boundary invalid")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(payloads) - {"MANIFEST.json", "SHA256SUMS"}:
            raise MaterializationError("sovereign file manifest invalid")
        if any(files[name] != sha256_bytes(payloads[name]) for name in files):
            raise MaterializationError("sovereign payload hash mismatch")
        parsed_sums: dict[str, str] = {}
        for line in sums:
            digest, separator, name = line.partition("  ")
            if not separator or len(digest) != 64 or name in parsed_sums:
                raise MaterializationError("sovereign SHA256SUMS invalid")
            parsed_sums[name] = digest
        if set(parsed_sums) != set(payloads) - {"SHA256SUMS"} or any(parsed_sums[name] != sha256_bytes(payloads[name]) for name in parsed_sums):
            raise MaterializationError("sovereign SHA256SUMS mismatch")
        creation = _creation_from_dict(creation_payload)
        if creation.creation_id != manifest.get("creation_id") or creation.version != manifest.get("creation_version"):
            raise MaterializationError("sovereign creation identity mismatch")
        _reject_secrets(creation.to_dict())
        return ImportedSovereignPackage(source, sha256_file(source), creation, manifest, payloads)


def build_staged_payloads(
    creation: CreationSpec,
    forge_receipt: ForgeReceipt,
    simulation_receipt: SimulationReceipt,
    agent: SovereignTAgentBundle,
    *,
    requirement_graph: Mapping[str, Any],
    evidence_receipts: Mapping[str, Any],
    t_receipt_hashes: tuple[str, ...],
) -> dict[str, bytes]:
    _reject_secrets(dict(requirement_graph))
    _reject_secrets(dict(evidence_receipts))
    payloads = {
        "creation.json": canonical_json(creation.to_dict()),
        "requirement-graph.json": canonical_json(dict(requirement_graph)),
        "evidence-receipts.json": canonical_json(dict(evidence_receipts)),
        "forge-receipt.json": canonical_json(forge_receipt.to_dict()),
        "simulation-receipt.json": canonical_json(simulation_receipt.to_dict()),
        "api.py": _api_source().encode("utf-8"),
        "index.html": _index_html().encode("utf-8"),
        **agent.payloads(),
    }
    sbom = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"casulo-sovereign-{creation.creation_id}",
        "documentNamespace": f"https://teloscorp.invalid/spdx/sovereign-{hashlib.sha256(creation.creation_id.encode()).hexdigest()}",
        "creationInfo": {"created": "1980-01-01T00:00:00Z", "creators": ["Organization: Teloscorp"]},
        "packages": [
            {"name": "Casulo T Runtime", "SPDXID": "SPDXRef-T-Runtime", "downloadLocation": "NOASSERTION", "licenseConcluded": "LicenseRef-Casulo-Private"},
            {"name": "Python stdlib launcher", "SPDXID": "SPDXRef-Python", "downloadLocation": "NOASSERTION", "licenseConcluded": "PSF-2.0"},
        ],
        "files": [{"fileName": name, "SPDXID": f"SPDXRef-File-{index}", "checksums": [{"algorithm": "SHA256", "checksumValue": sha256_bytes(payload)}]} for index, (name, payload) in enumerate(sorted(payloads.items()), 1)],
    }
    payloads["SBOM.spdx.json"] = canonical_json(sbom)
    payload_hashes = {name: sha256_bytes(payload) for name, payload in payloads.items()}
    tcap_root, tcap_manifest, typed = verify_tcap_v2(agent.tcap_root)
    manifest = {
        "schema": SCHEMA_V2,
        "package_id": f"creation-{hashlib.sha256(creation.creation_id.encode()).hexdigest()[:16]}-v{creation.version}-t85",
        "creation_id": creation.creation_id,
        "creation_version": creation.version,
        "spec_hash": creation.sha256,
        "requirement_graph_hash": sha256_bytes(payloads["requirement-graph.json"]),
        "evidence_receipts_hash": sha256_bytes(payloads["evidence-receipts.json"]),
        "engine_boundary": "portable-t-runtime-no-owner-engine",
        "real_effects_included": False,
        "secret_slots": [],
        "signature_class": SIGNATURE_CLASS,
        "capabilities": sorted(creation.capabilities),
        "T_source_hashes": [item["sha256"] for item in tcap_manifest["sources"]],
        "T_IR_hashes": [hashlib.sha256(canonical_json(item)).hexdigest() for item in typed["modules"]],
        "TCAP_hash": tcap_manifest["tcap_hash"],
        "runtime_sha256": sha256_file(agent.runtime_executable),
        "publish_authority_receipts": list(t_receipt_hashes),
        "provenance_root": simulation_receipt.head_hash,
        "targets": [
            {"target": "casulo-package", "supported": True, "entrypoint": "MANIFEST.json"},
            {"target": "cli", "supported": True, "entrypoint": "agent.py"},
            {"target": "api-loopback", "supported": True, "entrypoint": "api.py"},
            {"target": "local-service", "supported": True, "entrypoint": "api.py"},
            {"target": "desktop-web-local", "supported": True, "entrypoint": "index.html"},
        ],
        "import_compatibility": "casulo.materialized-package/2.x",
        "files": payload_hashes,
    }
    payloads["MANIFEST.json"] = canonical_json(manifest)
    payloads["SHA256SUMS"] = "".join(f"{sha256_bytes(payload)}  {name}\n" for name, payload in sorted(payloads.items())).encode("ascii")
    return payloads


def publish_payloads(output_root: Path, package_id: str, payloads: Mapping[str, bytes]) -> tuple[Path, Path]:
    root = output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / package_id).resolve()
    archive = (root / f"{package_id}.casulo.zip").resolve()
    if not destination.is_relative_to(root) or not archive.is_relative_to(root) or destination.exists() or archive.exists():
        raise MaterializationError("sovereign publish destination invalid or exists")
    staging = root / f".{package_id}.{os.getpid()}.staging"
    if staging.exists():
        raise MaterializationError("sovereign staging exists")
    staging.mkdir()
    try:
        for name, payload in payloads.items():
            relative = _safe_relative(name)
            path = staging.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        os.replace(staging, destination)
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for path in sorted(item for item in destination.rglob("*") if item.is_file()):
                relative = path.relative_to(destination).as_posix()
                info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                package.writestr(info, path.read_bytes())
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if destination.exists() and not archive.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination, archive


def _creation_from_dict(value: Mapping[str, Any]) -> CreationSpec:
    try:
        return CreationSpec(
            str(value["creation_id"]), int(value["version"]), CreationState(value["state"]),
            value["content"], frozenset(value["capabilities"]), tuple(value["rejected_delta_ids"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MaterializationError("sovereign CreationSpec invalid") from error


def _agent_launcher() -> str:
    return '''from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
DESCRIPTOR = json.loads((ROOT / "agent-descriptor.json").read_text(encoding="utf-8"))
def main():
    payload = json.loads(sys.stdin.read() or "{}")
    with tempfile.TemporaryDirectory(prefix="casulo-t-agent-") as temporary:
        input_path = Path(temporary) / "input.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\\n", encoding="utf-8")
        completed = subprocess.run([
            str(ROOT / DESCRIPTOR["runtime"]), str(ROOT / DESCRIPTOR["tcap_root"]),
            DESCRIPTOR["entry_module"] + "::" + DESCRIPTOR["entry_function"], str(input_path),
            "", "materialized_agent", "agent:" + DESCRIPTOR["agent_id"], "0" * 64,
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, timeout=30)
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr); return completed.returncode
    document = json.loads(completed.stdout)
    print(json.dumps(document, ensure_ascii=False, sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
'''


def _api_source() -> str:
    return '''from __future__ import annotations
import argparse, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({"ok": True, "bind": "loopback", "effects": "simulation-only"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
    def log_message(self, *_): pass
def main():
    p=argparse.ArgumentParser(); p.add_argument("--port", type=int, default=0); a=p.parse_args()
    s=ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(json.dumps({"bind":"127.0.0.1","port":s.server_port}), flush=True); s.serve_forever()
if __name__ == "__main__": main()
'''


def _index_html() -> str:
    return "<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>Casulo T85</title><body><h1>Criação Casulo T85</h1><p>Agente T portátil; efeitos reais desativados.</p></body></html>"
