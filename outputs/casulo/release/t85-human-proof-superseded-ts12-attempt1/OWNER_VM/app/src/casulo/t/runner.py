from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact import ArtifactError, verify_artifact


class ExecutionFailed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunResult:
    artifact_dir: Path
    artifact_id: str
    operation: str
    batch: bool
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LoadedArtifact:
    directory: Path
    manifest: dict[str, Any]
    namespace: dict[str, Any]


def run_artifact(
    artifact_dir: str | Path,
    payload: Any,
    operation: str | None = None,
    batch: bool | None = None,
    use_cache: bool = True,
) -> RunResult:
    loaded = load_artifact(artifact_dir)
    directory, manifest = loaded.directory, loaded.manifest
    selected = select_operation(manifest, operation)
    is_batch = isinstance(payload, list) if batch is None else batch
    function_name = "execute_batch" if is_batch else "execute"
    execute = loaded.namespace.get(function_name)
    if not callable(execute):
        raise ArtifactError(
            f"artefato não expõe {function_name}(operation, payload)"
        )
    try:
        result = execute(selected, payload, use_cache=use_cache)
    except Exception as exc:
        raise ExecutionFailed(str(exc)) from exc
    if not isinstance(result, dict):
        raise ExecutionFailed("artefato retornou envelope inválido")
    return RunResult(
        artifact_dir=directory,
        artifact_id=manifest["artifact_id"],
        operation=selected,
        batch=is_batch,
        payload=result,
    )


def load_artifact(artifact_dir: str | Path) -> LoadedArtifact:
    directory, manifest = verify_artifact(artifact_dir)
    executable = directory / manifest["executable"]["file"]
    namespace: dict[str, Any] = {
        "__file__": str(executable),
        "__name__": "_casulo_compiled_artifact",
        "__package__": None,
    }
    try:
        source = executable.read_text(encoding="utf-8")
        exec(compile(source, str(executable), "exec"), namespace)
    except Exception as exc:
        raise ExecutionFailed(str(exc)) from exc
    return LoadedArtifact(
        directory=directory,
        manifest=manifest,
        namespace=namespace,
    )


def select_operation(
    manifest: dict[str, Any],
    operation: str | None = None,
) -> str:
    available = tuple(
        entry["name"]
        for entry in manifest.get("operations", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    )
    selected = operation
    if selected is None:
        if len(available) == 1:
            selected = available[0]
        elif not available:
            raise ArtifactError("artefato não possui operações executáveis")
        else:
            raise ArtifactError(
                "artefato possui múltiplas operações; informe --operation"
            )
    if selected not in available:
        raise ArtifactError(
            f"operação desconhecida: {selected}; "
            f"disponíveis: {', '.join(available)}"
        )
    return selected
