from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__ as COMPILER_VERSION
from .api import check_file, parse_file
from .ast import EnumDecl, FieldDecl, RecordDecl
from .artifact import ArtifactBuilder
from .training import (
    TrainingError,
    build_training_artifact,
    parse_training_file,
)
from .typesys import SemanticType


WORKSPACE_FORMAT = "casulo-t-workspace/0.1"
WORKSPACE_BUILD_FORMAT = "casulo-t-workspace-build/0.1"
WORKSPACE_LOCK_FORMAT = "casulo-t-workspace-lock/0.1"
WORKSPACE_MANIFEST = "casulo.toml"
WORKSPACE_LOCK = "casulo.lock"
WORKSPACE_BUILD_MANIFEST = "workspace.json"
MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class WorkspaceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class EggProjectManifest:
    name: str
    version: str
    kind: str
    entry: str | None
    source_dir: str
    dependency_paths: tuple[str, ...]
    external_modules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EggModule:
    name: str
    path: Path
    project_root: Path
    kind: str
    uses: tuple[str, ...]
    source_sha256: str

    def to_dict(self, workspace_root: Path) -> dict[str, Any]:
        try:
            source = self.path.relative_to(workspace_root).as_posix()
        except ValueError:
            source = self.path.as_posix()
        return {
            "name": self.name,
            "source": source,
            "kind": self.kind,
            "uses": list(self.uses),
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class ModuleInterface:
    module: str
    exported_types: tuple[str, ...]
    record_fields: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LarvaWorkspace:
    root: Path
    manifest_path: Path
    manifest: EggProjectManifest
    modules: tuple[EggModule, ...]
    build_order: tuple[str, ...]
    interfaces: tuple[ModuleInterface, ...]

    @property
    def entry_module(self) -> EggModule:
        if self.manifest.entry is None:
            raise WorkspaceError(
                "T4013",
                "workspace não possui módulo de entrada",
            )
        for module in self.modules:
            if module.name == self.manifest.entry:
                return module
        raise WorkspaceError(
            "T4013",
            f"módulo de entrada não encontrado: {self.manifest.entry}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": WORKSPACE_FORMAT,
            "root": str(self.root),
            "manifest": self.manifest.to_dict(),
            "modules": [
                module.to_dict(self.root)
                for module in self.modules
            ],
            "build_order": list(self.build_order),
            "interfaces": [item.to_dict() for item in self.interfaces],
        }


@dataclass(frozen=True, slots=True)
class CrisalidaWorkspaceBuild:
    output_dir: Path
    workspace_id: str
    manifest: dict[str, Any]
    entry_artifact: Path
    entry_kind: str
    cache_hit: bool


def init_workspace(
    target: str | Path,
    *,
    name: str | None = None,
) -> Path:
    root = Path(target).expanduser().resolve()
    project_name = name or root.name.lower().replace("_", "-")
    if not PROJECT_PATTERN.fullmatch(project_name):
        raise WorkspaceError(
            "T4002",
            "nome do projeto deve usar letras minúsculas, números, '-' ou '_'",
        )
    module_prefix = project_name.replace("-", "_")
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise WorkspaceError(
                "T4003",
                f"destino não está vazio: {root}",
            )
    root.mkdir(parents=True, exist_ok=True)
    source_dir = root / "src"
    tests_dir = root / "tests"
    source_dir.mkdir()
    tests_dir.mkdir()
    manifest = (
        "[project]\n"
        f'name = "{project_name}"\n'
        'version = "0.1.0"\n'
        'kind = "application"\n'
        f'entry = "{module_prefix}.main"\n'
        'source = "src"\n'
        'external_modules = ["casulo.std"]\n'
        "\n"
        "[dependencies]\n"
    )
    main_source = (
        f"module {module_prefix}.main\n"
        "\n"
        "condense Main\n"
        "  emit true\n"
    )
    smoke_source = (
        f"module {module_prefix}.smoke\n"
        "\n"
        "condense Smoke\n"
        "  judge true\n"
        "  emit true\n"
    )
    (root / WORKSPACE_MANIFEST).write_text(
        manifest,
        encoding="utf-8",
        newline="\n",
    )
    (source_dir / "main.t").write_text(
        main_source,
        encoding="utf-8",
        newline="\n",
    )
    (tests_dir / "smoke.t").write_text(
        smoke_source,
        encoding="utf-8",
        newline="\n",
    )
    return root


def load_workspace(target: str | Path) -> LarvaWorkspace:
    root = _workspace_root(target)
    manifests: dict[Path, EggProjectManifest] = {}
    modules: dict[str, EggModule] = {}
    project_stack: list[Path] = []

    def load_project(project_root: Path) -> None:
        resolved_root = project_root.resolve()
        if resolved_root in project_stack:
            chain = " -> ".join(path.name for path in (*project_stack, resolved_root))
            raise WorkspaceError(
                "T4014",
                f"ciclo entre dependências locais: {chain}",
            )
        if resolved_root in manifests:
            return
        project_stack.append(resolved_root)
        manifest = _read_manifest(resolved_root)
        manifests[resolved_root] = manifest
        source_root = _safe_child(resolved_root, manifest.source_dir)
        if not source_root.is_dir():
            raise WorkspaceError(
                "T4004",
                f"diretório de fontes inexistente: {source_root}",
            )
        for source in sorted(source_root.rglob("*.t")):
            module = _read_module(source, resolved_root)
            previous = modules.get(module.name)
            if previous is not None:
                raise WorkspaceError(
                    "T4010",
                    f"módulo duplicado {module.name}: "
                    f"{previous.path} e {module.path}",
                )
            modules[module.name] = module
        for dependency in manifest.dependency_paths:
            load_project(
                _safe_child(
                    resolved_root,
                    dependency,
                    allow_parent=True,
                )
            )
        project_stack.pop()

    load_project(root)
    root_manifest = manifests[root]
    if root_manifest.kind == "application" and root_manifest.entry is None:
        raise WorkspaceError(
            "T4013",
            "projeto application exige project.entry",
        )
    if root_manifest.entry is not None and root_manifest.entry not in modules:
        raise WorkspaceError(
            "T4013",
            f"módulo de entrada não encontrado: {root_manifest.entry}",
        )
    external_prefixes = tuple(
        prefix
        for manifest in manifests.values()
        for prefix in manifest.external_modules
    )
    for module in modules.values():
        for dependency in module.uses:
            if dependency in modules:
                continue
            if any(
                dependency == prefix or dependency.startswith(prefix + ".")
                for prefix in external_prefixes
            ):
                continue
            raise WorkspaceError(
                "T4011",
                f"{module.name} usa módulo não resolvido: {dependency}",
            )
    order = _topological_order(modules)
    interfaces = _build_module_interfaces(modules)
    ordered_modules = tuple(modules[name] for name in sorted(modules))
    return LarvaWorkspace(
        root=root,
        manifest_path=root / WORKSPACE_MANIFEST,
        manifest=root_manifest,
        modules=ordered_modules,
        build_order=order,
        interfaces=interfaces,
    )


def check_workspace(target: str | Path) -> LarvaWorkspace:
    workspace = load_workspace(target)
    modules = {module.name: module for module in workspace.modules}
    interfaces = {item.module: item for item in workspace.interfaces}
    for module in workspace.modules:
        if module.kind == "training":
            try:
                parse_training_file(module.path)
            except TrainingError as error:
                raise WorkspaceError(
                    "T4021",
                    f"{module.name}: {error}",
                ) from error
            continue
        checked = check_file(
            module.path,
            imported_types=_linked_types(module, modules, interfaces),
            imported_records=_linked_records(module, modules, interfaces),
        )
        errors = [
            diagnostic.render()
            for diagnostic in checked.diagnostics
            if diagnostic.severity.value == "error"
        ]
        if errors:
            raise WorkspaceError(
                "T4020",
                f"{module.name} falhou na compilação:\n" + "\n".join(errors),
            )
    return workspace


def build_workspace(
    target: str | Path,
    output_dir: str | Path | None = None,
) -> CrisalidaWorkspaceBuild:
    workspace = check_workspace(target)
    seed = {
        "format": WORKSPACE_BUILD_FORMAT,
        "compiler": COMPILER_VERSION,
        "manifest": workspace.manifest.to_dict(),
        "modules": [
            module.to_dict(workspace.root)
            for module in workspace.modules
        ],
        "build_order": list(workspace.build_order),
        "interfaces": [item.to_dict() for item in workspace.interfaces],
    }
    digest = _sha256(_canonical_json(seed))
    workspace_id = f"sha256:{digest}"
    output = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else workspace.root / ".casulo" / "workspaces" / digest[:16]
    )
    existing = _existing_workspace_build(output, workspace_id)
    if existing is not None:
        return existing

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
    module_entries: list[dict[str, Any]] = []
    try:
        workspace_modules = {item.name: item for item in workspace.modules}
        workspace_interfaces = {
            item.module: item for item in workspace.interfaces
        }
        for module_name in workspace.build_order:
            module = next(
                item for item in workspace.modules if item.name == module_name
            )
            module_target = temporary / "modules" / Path(
                *module.name.split(".")
            )
            if module.kind == "training":
                artifact = build_training_artifact(
                    module.path,
                    module_target,
                )
                artifact_id = artifact.artifact_id
                artifact_manifest = artifact.manifest
            else:
                artifact = ArtifactBuilder().build(
                    module.path,
                    module_target,
                    imported_types=_linked_types(
                        module,
                        workspace_modules,
                        workspace_interfaces,
                    ),
                    imported_records=_linked_records(
                        module,
                        workspace_modules,
                        workspace_interfaces,
                    ),
                )
                artifact_id = artifact.artifact_id
                artifact_manifest = artifact.manifest
            module_entries.append(
                {
                    **module.to_dict(workspace.root),
                    "artifact_id": artifact_id,
                    "artifact": module_target.relative_to(
                        temporary
                    ).as_posix(),
                    "artifact_protocol": (
                        artifact_manifest.get("artifact_format")
                        or artifact_manifest.get("protocol")
                    ),
                }
            )
        entry = workspace.entry_module
        entry_record = next(
            item for item in module_entries if item["name"] == entry.name
        )
        document = {
            "format": WORKSPACE_BUILD_FORMAT,
            "workspace_id": workspace_id,
            "compiler": {
                "name": "T",
                "version": COMPILER_VERSION,
            },
            "brand": {
                "invention": "Casulo",
                "origin": "Teloscorp",
            },
            "project": workspace.manifest.to_dict(),
            "entry": {
                "module": entry.name,
                "kind": entry.kind,
                "artifact": entry_record["artifact"],
            },
            "build_order": list(workspace.build_order),
            "interfaces": [item.to_dict() for item in workspace.interfaces],
            "modules": module_entries,
        }
        (temporary / WORKSPACE_BUILD_MANIFEST).write_bytes(
            _canonical_json(document)
        )
        _write_lock(workspace, workspace_id)
        temporary.rename(output)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return CrisalidaWorkspaceBuild(
        output_dir=output,
        workspace_id=workspace_id,
        manifest=document,
        entry_artifact=output / entry_record["artifact"],
        entry_kind=entry.kind,
        cache_hit=False,
    )


def resolve_entry_source(
    target: str | Path,
    *,
    required_kind: str | None = None,
) -> Path:
    path = Path(target).expanduser().resolve()
    if path.is_file():
        return path
    workspace = check_workspace(path)
    entry = workspace.entry_module
    if required_kind is not None and entry.kind != required_kind:
        raise WorkspaceError(
            "T4022",
            f"entrada {entry.name} é {entry.kind}; esperado {required_kind}",
        )
    return entry.path


def test_workspace(target: str | Path) -> dict[str, Any]:
    workspace = check_workspace(target)
    tests_root = workspace.root / "tests"
    tests = tuple(sorted(tests_root.rglob("*.t"))) if tests_root.is_dir() else ()
    for test in tests:
        checked = check_file(test)
        failures = [
            diagnostic.render()
            for diagnostic in checked.diagnostics
            if diagnostic.severity.value == "error"
        ]
        if failures:
            raise WorkspaceError(
                "T4030",
                f"teste {test.name} falhou:\n" + "\n".join(failures),
            )
    return {
        "ok": True,
        "workspace": workspace.manifest.name,
        "modules_checked": len(workspace.modules),
        "tests_checked": len(tests),
    }


def _workspace_root(target: str | Path) -> Path:
    candidate = Path(target).expanduser().resolve()
    if candidate.is_file() and candidate.name == WORKSPACE_MANIFEST:
        candidate = candidate.parent
    manifest = candidate / WORKSPACE_MANIFEST
    if not manifest.is_file():
        raise WorkspaceError(
            "T4001",
            f"{WORKSPACE_MANIFEST} não encontrado em {candidate}",
        )
    return candidate


def _read_manifest(root: Path) -> EggProjectManifest:
    path = root / WORKSPACE_MANIFEST
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise WorkspaceError(
            "T4002",
            f"manifesto inválido em {path}: {error}",
        ) from error
    project = document.get("project")
    if not isinstance(project, dict):
        raise WorkspaceError("T4002", "tabela [project] é obrigatória")
    name = project.get("name")
    version = project.get("version")
    kind = project.get("kind", "application")
    entry = project.get("entry")
    source = project.get("source", "src")
    external = project.get("external_modules", ["casulo.std"])
    if not isinstance(name, str) or not PROJECT_PATTERN.fullmatch(name):
        raise WorkspaceError("T4002", "project.name inválido")
    if not isinstance(version, str) or not version:
        raise WorkspaceError("T4002", "project.version inválido")
    if kind not in {"application", "library"}:
        raise WorkspaceError(
            "T4002",
            "project.kind precisa ser application ou library",
        )
    if entry is not None and (
        not isinstance(entry, str) or not MODULE_PATTERN.fullmatch(entry)
    ):
        raise WorkspaceError("T4002", "project.entry inválido")
    if not isinstance(source, str) or not source:
        raise WorkspaceError("T4002", "project.source inválido")
    if not isinstance(external, list) or not all(
        isinstance(item, str) and MODULE_PATTERN.fullmatch(item)
        for item in external
    ):
        raise WorkspaceError("T4002", "project.external_modules inválido")
    dependencies = document.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise WorkspaceError("T4002", "[dependencies] precisa ser tabela")
    paths: list[str] = []
    for dependency_name, value in dependencies.items():
        if not isinstance(dependency_name, str):
            raise WorkspaceError("T4002", "nome de dependência inválido")
        if isinstance(value, str):
            dependency_path = value
        elif isinstance(value, dict) and isinstance(value.get("path"), str):
            dependency_path = value["path"]
        else:
            raise WorkspaceError(
                "T4002",
                f"dependência {dependency_name} exige path local",
            )
        paths.append(dependency_path)
    return EggProjectManifest(
        name=name,
        version=version,
        kind=kind,
        entry=entry,
        source_dir=source,
        dependency_paths=tuple(paths),
        external_modules=tuple(external),
    )


def _read_module(path: Path, project_root: Path) -> EggModule:
    source = path.read_text(encoding="utf-8")
    is_training = any(
        line.split("#", 1)[0].strip().startswith("learn ")
        for line in source.splitlines()
    )
    if is_training:
        try:
            spec = parse_training_file(path)
        except TrainingError as error:
            raise WorkspaceError("T4021", f"{path}: {error}") from error
        name = spec.module
        uses: tuple[str, ...] = ()
        kind = "training"
    else:
        parsed = parse_file(path)
        if parsed.program.module is None:
            raise WorkspaceError(
                "T4005",
                f"arquivo de workspace exige declaração module: {path}",
            )
        name = parsed.program.module.name
        uses = tuple(item.name for item in parsed.program.uses)
        kind = "core"
    return EggModule(
        name=name,
        path=path,
        project_root=project_root,
        kind=kind,
        uses=uses,
        source_sha256=_sha256(path.read_bytes()),
    )


def _build_module_interfaces(
    modules: dict[str, EggModule],
) -> tuple[ModuleInterface, ...]:
    result: list[ModuleInterface] = []
    for module in modules.values():
        exported_types: tuple[str, ...] = ()
        record_fields: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
        if module.kind == "core":
            parsed = parse_file(module.path)
            exported_types = tuple(
                sorted(
                    declaration.name
                    for declaration in parsed.program.declarations
                    if isinstance(declaration, (FieldDecl, RecordDecl, EnumDecl))
                )
            )
            record_fields = tuple(
                sorted(
                    (
                        declaration.name,
                        tuple(
                            (trace.name, SemanticType.from_ref(trace.type_ref).render())
                            for trace in declaration.traces
                        ),
                    )
                    for declaration in parsed.program.declarations
                    if isinstance(declaration, (FieldDecl, RecordDecl))
                )
            )
        payload = {
            "schema": "casulo-t-module-interface/1.0",
            "module": module.name,
            "exported_types": list(exported_types),
            "record_fields": [
                [name, [[field, type_name] for field, type_name in fields]]
                for name, fields in record_fields
            ],
        }
        result.append(
            ModuleInterface(
                module=module.name,
                exported_types=exported_types,
                record_fields=record_fields,
                sha256=_sha256(_canonical_json(payload)),
            )
        )
    return tuple(sorted(result, key=lambda item: item.module))


def _linked_types(
    module: EggModule,
    modules: dict[str, EggModule],
    interfaces: dict[str, ModuleInterface],
) -> frozenset[str]:
    origins: dict[str, str] = {}
    local = interfaces[module.name]
    for dependency in module.uses:
        if dependency not in modules:
            continue
        interface = interfaces[dependency]
        for type_name in interface.exported_types:
            previous = origins.get(type_name)
            if previous is not None and previous != dependency:
                raise WorkspaceError(
                    "T3103",
                    f"tipo importado ambíguo {type_name}: {previous} e {dependency}",
                )
            if type_name in local.exported_types:
                raise WorkspaceError(
                    "T3103",
                    f"tipo local colide com import {dependency}: {type_name}",
                )
            origins[type_name] = dependency
    return frozenset(origins)


def _linked_records(
    module: EggModule,
    modules: dict[str, EggModule],
    interfaces: dict[str, ModuleInterface],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for dependency in module.uses:
        if dependency not in modules:
            continue
        for type_name, fields in interfaces[dependency].record_fields:
            if type_name in result:
                raise WorkspaceError(
                    "T3103",
                    f"record importado ambíguo: {type_name}",
                )
            result[type_name] = dict(fields)
    return result


def _topological_order(modules: dict[str, EggModule]) -> tuple[str, ...]:
    state: dict[str, int] = {}
    result: list[str] = []
    stack: list[str] = []

    def visit(name: str) -> None:
        current = state.get(name, 0)
        if current == 2:
            return
        if current == 1:
            start = stack.index(name)
            cycle = " -> ".join((*stack[start:], name))
            raise WorkspaceError(
                "T4012",
                f"ciclo entre módulos: {cycle}",
            )
        state[name] = 1
        stack.append(name)
        for dependency in modules[name].uses:
            if dependency in modules:
                visit(dependency)
        stack.pop()
        state[name] = 2
        result.append(name)

    for module_name in sorted(modules):
        visit(module_name)
    return tuple(result)


def _existing_workspace_build(
    output: Path,
    workspace_id: str,
) -> CrisalidaWorkspaceBuild | None:
    if not output.exists():
        return None
    manifest_path = output / WORKSPACE_BUILD_MANIFEST
    if not manifest_path.is_file():
        raise WorkspaceError(
            "T4040",
            f"destino existente não é workspace compilado: {output}",
        )
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if document.get("workspace_id") != workspace_id:
        raise WorkspaceError(
            "T4040",
            f"destino contém outro workspace: {output}",
        )
    entry = document["entry"]
    artifact = output / entry["artifact"]
    if not artifact.is_dir():
        raise WorkspaceError(
            "T4041",
            f"artefato de entrada ausente: {artifact}",
        )
    return CrisalidaWorkspaceBuild(
        output_dir=output,
        workspace_id=workspace_id,
        manifest=document,
        entry_artifact=artifact,
        entry_kind=entry["kind"],
        cache_hit=True,
    )


def _write_lock(workspace: LarvaWorkspace, workspace_id: str) -> None:
    document = {
        "format": WORKSPACE_LOCK_FORMAT,
        "workspace_id": workspace_id,
        "compiler": COMPILER_VERSION,
        "project": workspace.manifest.name,
        "modules": [
            {
                "name": module.name,
                "kind": module.kind,
                "source_sha256": module.source_sha256,
            }
            for module in workspace.modules
        ],
    }
    payload = _canonical_json(document)
    path = workspace.root / WORKSPACE_LOCK
    temporary = path.with_suffix(".lock.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _safe_child(
    root: Path,
    relative: str,
    *,
    allow_parent: bool = False,
) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise WorkspaceError(
            "T4006",
            f"caminho precisa ser relativo: {relative}",
        )
    candidate = (root / relative).resolve()
    if not allow_parent and not candidate.is_relative_to(root):
        raise WorkspaceError(
            "T4006",
            f"caminho escapa do projeto: {relative}",
        )
    return candidate


def _canonical_json(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
