from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Mapping

from . import __version__ as COMPILER_VERSION
from .api import check_file
from .backend import (
    BACKEND_VERSION,
    STRUCTURAL_KEY_PROTOCOL,
    TYPED_BUFFER_PROTOCOL,
    BackendError,
    PythonBackend,
)
from .diagnostics import Diagnostic
from .graph import MetamorfoseGraph
from .ir import IRProgram
from .native import (
    NATIVE_ABI_FILE,
    NATIVE_ABI_PROTOCOL,
    NATIVE_BACKEND_VERSION,
    NATIVE_SOURCE_FILE,
    C99Backend,
    NativeError,
)


ARTIFACT_FORMAT = "casulo-artifact/0.8"
EXECUTABLE_FILE = "casulo_artifact.py"
GRAPH_FILE = "metamorfose.graph.json"
IR_FILE = "crisalida.ir.json"
MANIFEST_FILE = "manifest.json"
SOURCE_FILE = "source.t"


class ArtifactError(RuntimeError):
    pass


class CompilationFailed(ArtifactError):
    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("o programa T não passou pelos gates do compilador")


@dataclass(frozen=True, slots=True)
class BuildResult:
    output_dir: Path
    artifact_id: str
    manifest: dict[str, Any]
    cache_hit: bool


class ArtifactBuilder:
    def __init__(
        self,
        backend: PythonBackend | None = None,
        native_backend: C99Backend | None = None,
    ) -> None:
        self.backend = backend or PythonBackend()
        self.native_backend = native_backend or C99Backend()

    def build(
        self,
        source: str | Path,
        output_dir: str | Path | None = None,
        *,
        imported_types: frozenset[str] = frozenset(),
        imported_records: Mapping[str, Mapping[str, str]] | None = None,
    ) -> BuildResult:
        source_path = Path(source).expanduser().resolve()
        source_bytes = source_path.read_bytes()
        checked = check_file(
            source_path,
            imported_types=imported_types,
            imported_records=imported_records,
        )
        if (
            not checked.ok
            or checked.ir is None
            or checked.graph is None
        ):
            raise CompilationFailed(checked.diagnostics)

        ir_payload = canonical_ir_dict(checked.ir)
        ir_bytes = _canonical_json_bytes(ir_payload)
        graph_bytes = _canonical_json_bytes(checked.graph.to_dict())
        source_hash = _sha256(source_bytes)
        ir_hash = _sha256(ir_bytes)
        graph_hash = _sha256(graph_bytes)
        seed = {
            "artifact_format": ARTIFACT_FORMAT,
            "backend": BACKEND_VERSION,
            "compiler": COMPILER_VERSION,
            "graph_sha256": graph_hash,
            "ir_sha256": ir_hash,
            "native_backend": NATIVE_BACKEND_VERSION,
            "source_sha256": source_hash,
        }
        digest = _sha256(_canonical_json_bytes(seed))
        artifact_id = f"sha256:{digest}"
        generated = self.backend.generate(checked.ir, artifact_id)
        native_generated = self.native_backend.generate(
            checked.ir,
            artifact_id,
        )
        executable_bytes = generated.source.encode("utf-8")
        executable_hash = _sha256(executable_bytes)
        native_source_bytes = native_generated.source.encode("utf-8")
        native_source_hash = _sha256(native_source_bytes)
        native_abi_bytes = _canonical_json_bytes(native_generated.abi)
        native_abi_hash = _sha256(native_abi_bytes)

        manifest = {
            "artifact_format": ARTIFACT_FORMAT,
            "artifact_id": artifact_id,
            "brand": "Casulo",
            "origin": "Teloscorp",
            "compiler": {
                "name": "T",
                "version": COMPILER_VERSION,
            },
            "backend": {
                "name": "Python de referência",
                "version": generated.backend,
            },
            "source": {
                "encoding": "utf-8",
                "file": SOURCE_FILE,
                "sha256": source_hash,
            },
            "ir": {
                "file": IR_FILE,
                "sha256": ir_hash,
                "version": checked.ir.version,
            },
            "graph": {
                "file": GRAPH_FILE,
                "sha256": graph_hash,
                "version": checked.graph.version,
            },
            "executable": {
                "file": EXECUTABLE_FILE,
                "language": "python",
                "requires": ">=3.11",
                "sha256": executable_hash,
            },
            "native": {
                "backend": native_generated.backend,
                "protocol": NATIVE_ABI_PROTOCOL,
                "source": {
                    "file": NATIVE_SOURCE_FILE,
                    "language": "c99",
                    "sha256": native_source_hash,
                },
                "abi": {
                    "file": NATIVE_ABI_FILE,
                    "sha256": native_abi_hash,
                },
                "operations": native_generated.abi["operations"],
            },
            "module": checked.ir.module,
            "operations": operation_manifest(checked.ir, checked.graph),
        }
        if checked.ir.language != "T/1.0":
            manifest["language"] = checked.ir.language
            manifest["capability_requirements"] = list(checked.ir.capabilities)
            manifest["imported_types"] = sorted(imported_types)
            manifest["imported_records"] = {
                name: dict(sorted(fields.items()))
                for name, fields in sorted((imported_records or {}).items())
            }
        manifest_bytes = _canonical_json_bytes(manifest)

        target = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else (
                source_path.parent
                / ".casulo"
                / "build"
                / digest[:16]
            ).resolve()
        )
        files = {
            SOURCE_FILE: source_bytes,
            IR_FILE: ir_bytes,
            GRAPH_FILE: graph_bytes,
            EXECUTABLE_FILE: executable_bytes,
            NATIVE_SOURCE_FILE: native_source_bytes,
            NATIVE_ABI_FILE: native_abi_bytes,
            MANIFEST_FILE: manifest_bytes,
        }
        if target.exists():
            if _is_valid_cache(target, manifest, files):
                return BuildResult(
                    output_dir=target,
                    artifact_id=artifact_id,
                    manifest=manifest,
                    cache_hit=True,
                )
            raise ArtifactError(
                f"destino já existe e não é o mesmo artefato válido: {target}"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{target.name}.",
                dir=target.parent,
            )
        )
        try:
            for name, content in files.items():
                (temporary / name).write_bytes(content)
            temporary.rename(target)
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

        return BuildResult(
            output_dir=target,
            artifact_id=artifact_id,
            manifest=manifest,
            cache_hit=False,
        )


def canonical_ir_dict(program: IRProgram) -> dict[str, Any]:
    """Remove localização física sem retirar significado executável da IR."""

    return _without_spans(program.to_dict())


def read_manifest(artifact_dir: str | Path) -> dict[str, Any]:
    directory = Path(artifact_dir).expanduser().resolve()
    manifest_path = directory / MANIFEST_FILE
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError(
            f"manifesto de artefato inválido: {manifest_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ArtifactError(
            f"manifesto de artefato precisa ser um objeto: {manifest_path}"
        )
    if payload.get("artifact_format") != ARTIFACT_FORMAT:
        raise ArtifactError(
            f"formato de artefato não suportado: "
            f"{payload.get('artifact_format')!r}"
        )
    return payload


def verify_artifact(
    artifact_dir: str | Path,
) -> tuple[Path, dict[str, Any]]:
    directory = Path(artifact_dir).expanduser().resolve()
    manifest = read_manifest(directory)
    compiler = manifest.get("compiler")
    backend = manifest.get("backend")
    native = manifest.get("native")
    if not isinstance(compiler, dict) or compiler.get("version") != COMPILER_VERSION:
        raise ArtifactError(
            "versão do compilador no artefato não é suportada por este executor"
        )
    if not isinstance(backend, dict) or backend.get("version") != BACKEND_VERSION:
        raise ArtifactError(
            "versão do backend no artefato não é suportada por este executor"
        )
    if (
        not isinstance(native, dict)
        or native.get("backend") != NATIVE_BACKEND_VERSION
        or native.get("protocol") != NATIVE_ABI_PROTOCOL
    ):
        raise ArtifactError(
            "versão do backend C99 no artefato não é suportada por este executor"
        )
    verified_files: dict[str, tuple[Path, bytes]] = {}
    for section in ("source", "ir", "graph", "executable"):
        entry = manifest.get(section)
        if not isinstance(entry, dict):
            raise ArtifactError(f"seção ausente no manifesto: {section}")
        filename = entry.get("file")
        expected = entry.get("sha256")
        if not isinstance(filename, str) or not isinstance(expected, str):
            raise ArtifactError(f"seção inválida no manifesto: {section}")
        file_path = (directory / filename).resolve()
        if not file_path.is_relative_to(directory):
            raise ArtifactError(
                f"caminho externo bloqueado no manifesto: {filename}"
            )
        try:
            content = file_path.read_bytes()
            actual = _sha256(content)
        except OSError as exc:
            raise ArtifactError(
                f"arquivo ausente no artefato: {file_path}"
            ) from exc
        if actual != expected:
            raise ArtifactError(
                f"integridade violada em {filename}: "
                f"esperado {expected}, recebido {actual}"
            )
        verified_files[section] = (file_path, content)
    for section in ("source", "abi"):
        entry = native.get(section)
        if not isinstance(entry, dict):
            raise ArtifactError(f"seção nativa ausente no manifesto: {section}")
        filename = entry.get("file")
        expected = entry.get("sha256")
        if not isinstance(filename, str) or not isinstance(expected, str):
            raise ArtifactError(f"seção nativa inválida no manifesto: {section}")
        file_path = (directory / filename).resolve()
        if not file_path.is_relative_to(directory):
            raise ArtifactError(
                f"caminho externo bloqueado no manifesto: {filename}"
            )
        try:
            content = file_path.read_bytes()
        except OSError as exc:
            raise ArtifactError(f"arquivo nativo ausente: {file_path}") from exc
        if _sha256(content) != expected:
            raise ArtifactError(f"integridade violada em {filename}")
        verified_files[f"native_{section}"] = (file_path, content)

    expected_id = "sha256:" + _sha256(
        _canonical_json_bytes(
            {
                "artifact_format": ARTIFACT_FORMAT,
                "backend": backend["version"],
                "compiler": compiler["version"],
                "graph_sha256": manifest["graph"]["sha256"],
                "ir_sha256": manifest["ir"]["sha256"],
                "native_backend": native["backend"],
                "source_sha256": manifest["source"]["sha256"],
            }
        )
    )
    if manifest.get("artifact_id") != expected_id:
        raise ArtifactError(
            "artifact_id não corresponde à fonte, à IR e às versões declaradas"
        )

    source_path, _ = verified_files["source"]
    imported_types_value = manifest.get("imported_types", [])
    if not isinstance(imported_types_value, list) or any(
        not isinstance(item, str) for item in imported_types_value
    ):
        raise ArtifactError("imported_types inválido no manifesto")
    imported_records_value = manifest.get("imported_records", {})
    if not isinstance(imported_records_value, dict) or any(
        not isinstance(name, str)
        or not isinstance(fields, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in fields.items())
        for name, fields in imported_records_value.items()
    ):
        raise ArtifactError("imported_records inválido no manifesto")
    checked = check_file(
        source_path,
        imported_types=frozenset(imported_types_value),
        imported_records=imported_records_value,
    )
    if (
        not checked.ok
        or checked.ir is None
        or checked.graph is None
    ):
        raise ArtifactError(
            "fonte preservada não recompila com o compilador declarado"
        )
    expected_ir = _canonical_json_bytes(canonical_ir_dict(checked.ir))
    if verified_files["ir"][1] != expected_ir:
        raise ArtifactError(
            "CrisálidaIR não corresponde à fonte preservada"
        )
    expected_graph = _canonical_json_bytes(checked.graph.to_dict())
    if verified_files["graph"][1] != expected_graph:
        raise ArtifactError(
            "grafo da Metamorfose não corresponde à fonte preservada"
        )
    try:
        expected_executable = PythonBackend().generate(
            checked.ir,
            expected_id,
        ).source.encode("utf-8")
    except BackendError as exc:
        raise ArtifactError(
            "fonte preservada não pode ser regenerada pelo backend declarado"
        ) from exc
    if verified_files["executable"][1] != expected_executable:
        raise ArtifactError(
            "executável não corresponde à fonte e à CrisálidaIR"
        )
    try:
        expected_native = C99Backend().generate(checked.ir, expected_id)
    except NativeError as exc:
        raise ArtifactError(
            "fonte preservada não pode ser regenerada pelo backend C99"
        ) from exc
    expected_native_source = expected_native.source.encode("utf-8")
    expected_native_abi = _canonical_json_bytes(expected_native.abi)
    if verified_files["native_source"][1] != expected_native_source:
        raise ArtifactError(
            "fonte C99 não corresponde à fonte e à CrisálidaIR"
        )
    if verified_files["native_abi"][1] != expected_native_abi:
        raise ArtifactError(
            "ABI nativa não corresponde à fonte e à CrisálidaIR"
        )
    if native.get("operations") != expected_native.abi["operations"]:
        raise ArtifactError(
            "índice nativo do manifesto não corresponde à ABI regenerada"
        )

    expected_operations = operation_manifest(checked.ir, checked.graph)
    if (
        manifest.get("module") != checked.ir.module
        or manifest.get("operations") != expected_operations
    ):
        raise ArtifactError(
            "índice de operações do manifesto não corresponde à CrisálidaIR"
        )
    if checked.ir.language != "T/1.0" and (
        manifest.get("language") != checked.ir.language
        or manifest.get("capability_requirements")
        != list(checked.ir.capabilities)
        or manifest.get("imported_types") != sorted(imported_types_value)
        or manifest.get("imported_records") != imported_records_value
    ):
        raise ArtifactError("requirements de capability divergem da CrisálidaIR")
    return directory, manifest


def operation_manifest(
    program: IRProgram,
    graph: MetamorfoseGraph,
) -> list[dict[str, Any]]:
    graph_by_name = {
        operation.name: operation
        for operation in graph.operations
    }
    schemas = {
        field.name: {
            trace.name: trace.type_name
            for trace in field.traces
        }
        for field in program.fields
    }
    schemas.update(
        {
            record.name: {
                trace.name: trace.type_name
                for trace in record.traces
            }
            for record in program.records
        }
    )
    result = [
        {
            "input_type": operation.input_type,
            "kind": operation.kind,
            "name": operation.name,
            "output_type": operation.output_type,
            "target_type": operation.target_type,
            "optimization": {
                "cacheable": graph_by_name[operation.name].cacheable,
                "deterministic": graph_by_name[operation.name].deterministic,
                "effects": list(graph_by_name[operation.name].effects),
                "estimated_cost": graph_by_name[operation.name].estimated_cost,
                "key_protocol": STRUCTURAL_KEY_PROTOCOL,
                "cache_scope": "batch-local",
                "buffer_protocol": (
                    TYPED_BUFFER_PROTOCOL
                    if PythonBackend._supports_typed_buffer(
                        operation,
                        schemas,
                    )
                    else None
                ),
                "manifestation": (
                    "boundary"
                    if PythonBackend._supports_typed_buffer(
                        operation,
                        schemas,
                    )
                    else "inline"
                ),
            },
        }
        for operation in program.operations
    ]
    if program.language != "T/1.0":
        for entry, operation in zip(result, graph.operations, strict=True):
            entry["capability_effects"] = list(operation.permissions)
    return result


def _is_valid_cache(
    directory: Path,
    expected_manifest: dict[str, Any],
    expected_files: dict[str, bytes],
) -> bool:
    try:
        current_manifest = json.loads(
            (directory / MANIFEST_FILE).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if current_manifest != expected_manifest:
        return False
    for name, content in expected_files.items():
        try:
            if (directory / name).read_bytes() != content:
                return False
        except OSError:
            return False
    return True


def _without_spans(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_spans(item)
            for key, item in value.items()
            if key != "span"
        }
    if isinstance(value, list):
        return [_without_spans(item) for item in value]
    if isinstance(value, tuple):
        return [_without_spans(item) for item in value]
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
