from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .expression_ast import (
    BinaryNode,
    BooleanNode,
    CompareNode,
    ExpressionNode,
    ExpressionSyntaxError,
    LiteralNode,
    NameNode,
    UnaryNode,
    expression_names,
    parse_expression,
)
from .ir import IRInstruction, IROperation, IRProgram


NATIVE_ABI_PROTOCOL = "casulo-native-abi/0.1"
NATIVE_BACKEND_VERSION = "c99-simd/0.3"
NATIVE_ABI_VERSION = 1
NATIVE_BUILD_PROTOCOL = "casulo-native-build/0.5"
NATIVE_AOT_PROTOCOL = "casulo-aot/0.1"
NATIVE_ARENA_PROTOCOL = "casulo-native-arena/0.1"
NATIVE_BOUNDARY_AOT_PROTOCOL = "casulo-boundary-aot/0.1"
NATIVE_SIMD_PROTOCOL = "casulo-simd/0.1"
NATIVE_SOURCE_FILE = "casulo_native.c"
NATIVE_ABI_FILE = "casulo_native.abi.json"
NATIVE_CACHE_DIR = ".casulo-native"


class NativeError(RuntimeError):
    pass


class NativeUnavailable(NativeError):
    pass


class NativeCompilationError(NativeError):
    pass


class NativeSemanticError(NativeError):
    """O kernel executou corretamente e uma guarda T bloqueou o registro."""


@dataclass(frozen=True, slots=True)
class GeneratedNativeModule:
    backend: str
    source: str
    abi: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NativeBuild:
    library: Path
    compiler: str
    compiler_version: str
    command: tuple[str, ...]
    binary_sha256: str
    cache_hit: bool
    profile: str
    target: str
    vectorization_report: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["library"] = str(self.library)
        return payload


@dataclass(frozen=True, slots=True)
class NativeRunResult:
    artifact_dir: Path
    artifact_id: str
    operation: str
    batch: bool
    backend: str
    fallback_reason: str | None
    native_build: NativeBuild | None
    payload: dict[str, Any]


class C99Backend:
    """Gera uma fronteira C99 mínima e auditável a partir da CrisálidaIR."""

    def generate(
        self,
        program: IRProgram,
        artifact_id: str,
    ) -> GeneratedNativeModule:
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
        operations: list[dict[str, Any]] = []
        rendered_cases: list[str] = []
        for index, operation in enumerate(program.operations):
            metadata, rendered = self._operation(
                index,
                operation,
                schemas,
            )
            operations.append(metadata)
            if rendered is not None:
                rendered_cases.extend(rendered)

        abi = {
            "protocol": NATIVE_ABI_PROTOCOL,
            "abi_version": NATIVE_ABI_VERSION,
            "backend": NATIVE_BACKEND_VERSION,
            "layout": {
                "input": "column-major-float64",
                "column_stride": "records",
                "result": "float64[records]",
                "state": "uint8[records]",
                "evidence": "evidence-major-uint8",
                "stabilized": "evidence-major-float64",
            },
            "status": {
                "0": "ok",
                "1": "judge_failed",
                "2": "restriction_failed",
                "-1": "invalid_argument",
                "-2": "unknown_operation",
                "-3": "operation_not_native",
            },
            "operations": operations,
        }
        source = self._render_source(artifact_id, rendered_cases)
        return GeneratedNativeModule(
            backend=NATIVE_BACKEND_VERSION,
            source=source,
            abi=abi,
        )

    def _operation(
        self,
        index: int,
        operation: IROperation,
        schemas: dict[str, dict[str, str]],
    ) -> tuple[dict[str, Any], list[str] | None]:
        schema = schemas.get(operation.input_type or "")
        reason = _ineligibility_reason(operation, schema)
        fields = tuple(schema or ())
        judgements = tuple(
            instruction
            for instruction in operation.instructions
            if instruction.op == "judge"
        )
        restrictions = tuple(
            instruction
            for instruction in operation.instructions
            if instruction.op == "restrict"
        )
        stabilized = tuple(
            instruction
            for instruction in operation.instructions
            if instruction.op == "stabilize"
        )
        metadata = {
            "index": index,
            "name": operation.name,
            "eligible": reason is None,
            "reason": reason,
            "input_type": operation.input_type,
            "input_fields": list(fields),
            "output_type": operation.output_type,
            "judgements": [
                instruction.arguments[0] for instruction in judgements
            ],
            "restrictions": [
                instruction.arguments[0] for instruction in restrictions
            ],
            "stabilized": [
                instruction.arguments[0] for instruction in stabilized
            ],
            "vectorization": {
                "protocol": NATIVE_SIMD_PROTOCOL,
                "independent_records": reason is None,
                "guard_phase": bool(judgements or restrictions),
                "floating_point": "strict-no-reassociation",
            },
        }
        if reason is not None:
            return metadata, None

        optimized_instructions, aot = _remove_dead_lets(
            operation.instructions
        )
        metadata["aot"] = aot
        input_names = {
            name: f"casulo_input[{field_index}u * column_stride + record]"
            for field_index, name in enumerate(fields)
        }
        body = [
            f"    case {index}u:",
        ]
        guard_instructions = _guard_phase_instructions(
            optimized_instructions
        )
        if guard_instructions:
            names = dict(input_names)
            body.append(
                "        for (record = 0u; record < records; ++record) {"
            )
            judgement_index = 0
            restriction_index = 0
            for local_index, instruction in enumerate(guard_instructions):
                expression = _render_c_expression(
                    instruction.arguments[0],
                    names,
                )
                if instruction.op == "let":
                    local = f"casulo_guard_local_{local_index}"
                    body.append(
                        f"            const double {local} = {expression};"
                    )
                    if instruction.result is not None:
                        names[instruction.result] = local
                else:
                    status = 1 if instruction.op == "judge" else 2
                    evidence_index = (
                        judgement_index
                        if instruction.op == "judge"
                        else restriction_index
                    )
                    buffer_name = (
                        "judgements"
                        if instruction.op == "judge"
                        else "restrictions"
                    )
                    body.extend(
                        [
                            f"            if (!({expression})) {{",
                            "                *failed_record = record;",
                            (
                                "                *failed_instruction = "
                                f"{evidence_index}u;"
                            ),
                            f"                return {status};",
                            "            }",
                            (
                                f"            {buffer_name}[{evidence_index}u * "
                                "records + record] = 1u;"
                            ),
                        ]
                    )
                    if instruction.op == "judge":
                        judgement_index += 1
                    else:
                        restriction_index += 1
            body.append("        }")

        names = dict(input_names)
        body.append(
            "        for (record = 0u; record < records; ++record) {"
        )
        judgement_index = 0
        restriction_index = 0
        stabilized_index = 0
        emitted = False
        constants: dict[str, float] = {}
        for local_index, instruction in enumerate(optimized_instructions):
            expression = _render_c_expression(
                instruction.arguments[0],
                names,
            )
            if instruction.op == "let":
                parsed = parse_expression(instruction.arguments[0])
                constant = _constant_expression(parsed, constants)
                if constant is not None and instruction.result is not None:
                    names[instruction.result] = _render_c_number(constant)
                    constants[instruction.result] = constant
                    aot["constants_propagated"] += 1
                    continue
                if (
                    isinstance(parsed, NameNode)
                    and instruction.result is not None
                ):
                    names[instruction.result] = expression
                    constants.pop(instruction.result, None)
                    aot["aliases_propagated"] += 1
                    continue
                local = f"casulo_local_{local_index}"
                body.append(f"            const double {local} = {expression};")
                if instruction.result is not None:
                    names[instruction.result] = local
                    constants.pop(instruction.result, None)
            elif instruction.op in {"judge", "restrict"}:
                if instruction.op == "judge":
                    judgement_index += 1
                else:
                    restriction_index += 1
            elif instruction.op == "stabilize":
                body.extend(
                    [
                        (
                            f"            stabilized[{stabilized_index}u * "
                            f"records + record] = {expression};"
                        ),
                        "            states[record] = 1u;",
                    ]
                )
                stabilized_index += 1
            elif instruction.op == "emit":
                body.append(f"            results[record] = {expression};")
                emitted = True
        if not emitted:
            raise NativeError(
                f"operação elegível terminou sem emit: {operation.name}"
            )
        body.extend(["        }", "        return 0;"])
        return metadata, body

    @staticmethod
    def _render_source(
        artifact_id: str,
        cases: list[str],
    ) -> str:
        lines = [
            "/* Gerado pelo compilador T da Teloscorp / Casulo. */",
            "#include <stddef.h>",
            "#include <stdint.h>",
            "",
            "#if defined(_WIN32)",
            "#  define CASULO_EXPORT __declspec(dllexport)",
            "#else",
            "#  define CASULO_EXPORT __attribute__((visibility(\"default\")))",
            "#endif",
            "",
            "#if defined(_MSC_VER)",
            "#  define CASULO_RESTRICT __restrict",
            "#else",
            "#  define CASULO_RESTRICT restrict",
            "#endif",
            "",
            f"#define CASULO_NATIVE_ABI_VERSION {NATIVE_ABI_VERSION}u",
            "",
            "CASULO_EXPORT uint32_t casulo_abi_version(void) {",
            "    return CASULO_NATIVE_ABI_VERSION;",
            "}",
            "",
            "CASULO_EXPORT const char *casulo_artifact_id(void) {",
            f'    return "{artifact_id}";',
            "}",
            "",
            "CASULO_EXPORT int32_t casulo_execute_f64(",
            "    uint32_t operation,",
            "    size_t records,",
            "    const double * CASULO_RESTRICT casulo_input,",
            "    size_t column_stride,",
            "    double * CASULO_RESTRICT results,",
            "    double * CASULO_RESTRICT stabilized,",
            "    uint8_t * CASULO_RESTRICT states,",
            "    uint8_t * CASULO_RESTRICT judgements,",
            "    uint8_t * CASULO_RESTRICT restrictions,",
            "    size_t *failed_record,",
            "    uint32_t *failed_instruction",
            ") {",
            "    size_t record;",
            "    if (casulo_input == NULL || results == NULL ||",
            "        states == NULL || failed_record == NULL ||",
            "        failed_instruction == NULL || column_stride < records) {",
            "        return -1;",
            "    }",
            "    switch (operation) {",
            *cases,
            "    default:",
            "        return -2;",
            "    }",
            "}",
            "",
        ]
        return "\n".join(lines)


def compile_native_artifact(
    artifact_dir: str | Path,
    *,
    force: bool = False,
    profile: str = "simd",
) -> NativeBuild:
    from .artifact import verify_artifact

    directory, manifest = verify_artifact(artifact_dir)
    native = manifest.get("native")
    if not isinstance(native, dict):
        raise NativeUnavailable("artefato não contém backend C99")
    compiler = _find_compiler()
    compiler_version = _compiler_version(compiler)
    if profile not in {"scalar", "simd"}:
        raise NativeError(f"perfil nativo desconhecido: {profile}")
    target = _native_target(profile)
    source = directory / native["source"]["file"]
    source_sha256 = native["source"]["sha256"]
    platform_tag = _platform_tag()
    compiler_key = _sha256(
        (
            str(compiler)
            + "\n"
            + compiler_version
            + "\n"
            + profile
            + "\n"
            + target
        ).encode("utf-8")
    )[:16]
    build_key = _sha256(NATIVE_BUILD_PROTOCOL.encode("ascii"))[:8]
    artifact_key = manifest["artifact_id"].split(":", 1)[-1][:24]
    target_dir = (
        _native_cache_root()
        / artifact_key
        / platform_tag
        / f"{build_key}-{compiler_key}-{source_sha256[:16]}"
    )
    library_name = (
        "casulo_native.dll"
        if os.name == "nt"
        else (
            "libcasulo_native.dylib"
            if platform.system() == "Darwin"
            else "libcasulo_native.so"
        )
    )
    library = target_dir / library_name
    provenance = target_dir / "build.json"
    if not force and library.is_file() and provenance.is_file():
        try:
            saved = json.loads(provenance.read_text(encoding="utf-8"))
            binary_sha256 = _sha256(library.read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        else:
            if (
                saved.get("protocol") == NATIVE_BUILD_PROTOCOL
                and saved.get("source_sha256") == source_sha256
                and saved.get("binary_sha256") == binary_sha256
                and saved.get("compiler_version") == compiler_version
                and saved.get("profile") == profile
                and saved.get("target") == target
            ):
                return NativeBuild(
                    library=library,
                    compiler=str(compiler),
                    compiler_version=compiler_version,
                    command=tuple(saved["command"]),
                    binary_sha256=binary_sha256,
                    cache_hit=True,
                    profile=profile,
                    target=target,
                    vectorization_report=tuple(
                        saved.get("vectorization_report", ())
                    ),
                )

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target_dir.name}.", dir=target_dir.parent)
    )
    temporary_library = temporary / library_name
    vector_report_path = temporary / "vectorization.txt"
    command = _compile_command(
        compiler,
        source,
        temporary_library,
        profile=profile,
        vector_report=vector_report_path,
    )
    process = subprocess.run(
        command,
        cwd=temporary,
        capture_output=True,
        check=False,
        text=True,
    )
    if process.returncode != 0 or not temporary_library.is_file():
        shutil.rmtree(temporary, ignore_errors=True)
        detail = (process.stderr or process.stdout).strip()
        raise NativeCompilationError(
            f"compilação C99 falhou ({process.returncode}): {detail}"
        )
    vectorization_report = _vectorization_report(
        vector_report_path,
        process.stdout,
        process.stderr,
        source,
    )
    binary_sha256 = _sha256(temporary_library.read_bytes())
    portable_command = _portable_command(
        command,
        source,
        temporary_library,
        vector_report_path,
    )
    saved = {
        "protocol": NATIVE_BUILD_PROTOCOL,
        "artifact_id": manifest["artifact_id"],
        "source_sha256": source_sha256,
        "compiler": str(compiler),
        "compiler_version": compiler_version,
        "command": portable_command,
        "binary_sha256": binary_sha256,
        "platform": platform_tag,
        "profile": profile,
        "target": target,
        "vectorization_report": list(vectorization_report),
    }
    (temporary / "build.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if target_dir.exists():
        existing_library = target_dir / library_name
        try:
            existing_hash = _sha256(existing_library.read_bytes())
        except OSError as exc:
            shutil.rmtree(temporary, ignore_errors=True)
            raise NativeCompilationError(
                "cache nativo imutável existe, mas não pode ser validado"
            ) from exc
        if existing_hash != binary_sha256:
            shutil.rmtree(temporary, ignore_errors=True)
            raise NativeCompilationError(
                "compilação não reproduzível: o mesmo endereço de cache "
                "produziu SHA-256 diferente"
            )
        shutil.rmtree(temporary, ignore_errors=True)
    else:
        try:
            temporary.rename(target_dir)
        except FileExistsError:
            # Outra compilação venceu a corrida; o conteúdo precisa ser igual.
            existing_hash = _sha256((target_dir / library_name).read_bytes())
            shutil.rmtree(temporary, ignore_errors=True)
            if existing_hash != binary_sha256:
                raise NativeCompilationError(
                    "corrida de compilação produziu binários divergentes"
                )
    return NativeBuild(
        library=library,
        compiler=str(compiler),
        compiler_version=compiler_version,
        command=tuple(portable_command),
        binary_sha256=binary_sha256,
        cache_hit=False,
        profile=profile,
        target=target,
        vectorization_report=vectorization_report,
    )


def run_native_artifact(
    artifact_dir: str | Path,
    payload: Any,
    operation: str | None = None,
    *,
    batch: bool | None = None,
    fallback: bool = True,
) -> NativeRunResult:
    from .runner import load_artifact, select_operation

    loaded = load_artifact(artifact_dir)
    selected = select_operation(loaded.manifest, operation)
    is_batch = isinstance(payload, list) if batch is None else batch
    payloads = payload if is_batch else [payload]
    if not isinstance(payloads, list):
        raise NativeError("lote nativo precisa ser uma lista")
    native_entry = _native_operation(loaded.manifest, selected)
    if not native_entry.get("eligible"):
        reason = str(
            native_entry.get("reason") or "operação inelegível"
        )
        if not fallback:
            raise NativeUnavailable(reason)
        return _python_fallback(loaded, selected, payloads, is_batch, reason)
    try:
        build = compile_native_artifact(loaded.directory)
        items, arena_capacity = _execute_library(
            build.library,
            loaded.manifest,
            native_entry,
            payloads,
        )
    except NativeSemanticError:
        raise
    except (NativeError, OSError) as exc:
        if not fallback:
            raise
        return _python_fallback(
            loaded,
            selected,
            payloads,
            is_batch,
            str(exc),
        )

    result_payload = (
        {
            "artifact_id": loaded.manifest["artifact_id"],
            "module": loaded.manifest.get("module"),
            "operation": selected,
            "count": len(items),
            "cache": {
                "enabled": False,
                "hits": 0,
                "misses": len(items),
                "entries": 0,
                "key_protocol": None,
                "scope": None,
                "collision_verified": False,
                "buffer_protocol": NATIVE_ABI_PROTOCOL,
                "representation": "columnar-float64-native",
                "evidence_layout": "lateral-native",
                "hot_path": {
                    "records": len(items),
                    "native_calls": 1,
                    "arena_protocol": NATIVE_ARENA_PROTOCOL,
                    "boundary_aot_protocol": NATIVE_BOUNDARY_AOT_PROTOCOL,
                    "simd_protocol": NATIVE_SIMD_PROTOCOL,
                    "native_profile": build.profile,
                    "native_target": build.target,
                    "arena_capacity": arena_capacity,
                    "validation_and_marshal_passes": 1,
                },
            },
            "items": items,
        }
        if is_batch
        else items[0]
    )
    return NativeRunResult(
        artifact_dir=loaded.directory,
        artifact_id=loaded.manifest["artifact_id"],
        operation=selected,
        batch=is_batch,
        backend=NATIVE_BACKEND_VERSION,
        fallback_reason=None,
        native_build=build,
        payload=result_payload,
    )


def _execute_library(
    library_path: Path,
    manifest: dict[str, Any],
    operation: dict[str, Any],
    payloads: list[dict[str, float]],
) -> tuple[list[dict[str, Any]], int]:
    prepared = _load_prepared_executor(
        library_path,
        manifest,
        operation,
    )
    return prepared(payloads), prepared.capacity


class PreparedNativeExecutor:
    """Arena reutilizável para marshal, kernel e manifestação."""

    def __init__(
        self,
        library: Any,
        execute: Any,
        manifest: dict[str, Any],
        operation: dict[str, Any],
    ) -> None:
        self.library = library
        self.execute = execute
        self.manifest = manifest
        self.operation = operation
        self.capacity = 0
        self.count = 0
        self.input_buffer: Any = None
        self.results: Any = None
        self.stabilized: Any = None
        self.states: Any = None
        self.judgements: Any = None
        self.restrictions: Any = None
        self.failed_record = ctypes.c_size_t(0)
        self.failed_instruction = ctypes.c_uint32(0)
        self._marshal_into = _build_boundary_marshaller(
            tuple(operation["input_fields"])
        )
        self._manifest_from_buffers = _build_boundary_manifestation(
            operation
        )

    def __call__(
        self,
        payloads: list[dict[str, float]],
    ) -> list[dict[str, Any]]:
        count = self.marshal(payloads)
        self.kernel(count)
        return self.manifest_items(payloads, count)

    def marshal(self, payloads: list[dict[str, float]]) -> int:
        count = len(payloads)
        self._ensure_capacity(count)
        self._marshal_into(
            payloads,
            self.input_buffer,
            self.capacity,
        )
        self.count = count
        return count

    def kernel(self, count: int | None = None) -> None:
        records = self.count if count is None else count
        status = self.execute(
            self.operation["index"],
            records,
            self.input_buffer,
            self.capacity,
            self.results,
            self.stabilized,
            self.states,
            self.judgements,
            self.restrictions,
            ctypes.byref(self.failed_record),
            ctypes.byref(self.failed_instruction),
        )
        if status in {1, 2}:
            kind = "judge" if status == 1 else "restrict"
            expressions = (
                self.operation["judgements"]
                if status == 1
                else self.operation["restrictions"]
            )
            expression = expressions[self.failed_instruction.value]
            raise NativeSemanticError(
                f"{kind} falhou em {self.operation['name']}: {expression} "
                f"(registro {self.failed_record.value})"
            )
        if status != 0:
            raise NativeError(f"DLL nativa retornou status {status}")

    def manifest_items(
        self,
        payloads: list[dict[str, float]],
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        records = self.count if count is None else count
        return self._manifest_from_buffers(
            payloads,
            records,
            self.results,
            self.stabilized,
            self.manifest["artifact_id"],
            self.manifest.get("module"),
            self.operation["name"],
        )

    def _ensure_capacity(self, count: int) -> None:
        if count <= self.capacity and self.capacity > 0:
            return
        capacity = max(1, 1 << (count - 1).bit_length())
        operation = self.operation
        field_count = len(operation["input_fields"])
        stabilized_count = len(operation["stabilized"])
        judgement_count = len(operation["judgements"])
        restriction_count = len(operation["restrictions"])
        self.capacity = capacity
        self.input_buffer = (
            ctypes.c_double * max(1, capacity * field_count)
        )()
        self.results = (ctypes.c_double * capacity)()
        self.stabilized = (
            ctypes.c_double * max(1, capacity * stabilized_count)
        )()
        self.states = (ctypes.c_uint8 * capacity)()
        self.judgements = (
            ctypes.c_uint8 * max(1, capacity * judgement_count)
        )()
        self.restrictions = (
            ctypes.c_uint8 * max(1, capacity * restriction_count)
        )()


def _build_boundary_marshaller(fields: tuple[str, ...]) -> Any:
    lines = [
        "def _marshal(payloads, buffer, capacity):",
        "    for record, item in enumerate(payloads):",
        (
            f"        if type(item) is not dict or "
            f"len(item) != {len(fields)}:"
        ),
        "            raise _NativeUnavailable(",
        "                f'registro {record}: esquema exato exigido pela ABI nativa'",
        "            )",
        "        try:",
        *[
            f"            value_{index} = item[{field!r}]"
            for index, field in enumerate(fields)
        ],
        "        except KeyError as exc:",
        "            raise _NativeUnavailable(",
        "                f'registro {record}: esquema exato exigido pela ABI nativa'",
        "            ) from exc",
    ]
    for index, field in enumerate(fields):
        lines.extend(
            [
                (
                    f"        if type(value_{index}) is not float "
                    f"or not _isfinite(value_{index}):"
                ),
                "            raise _NativeUnavailable(",
                (
                    f"                f'registro {{record}}.{field}: "
                    "ABI 0.1 exige float finito; inteiros preservam "
                    "semântica pelo fallback'"
                ),
                "            )",
                (
                    f"        buffer[{index} * capacity + record] = "
                    f"value_{index}"
                ),
            ]
        )
    namespace: dict[str, Any] = {}
    exec(
        compile(
            "\n".join(lines) + "\n",
            "<casulo-boundary-marshaller>",
            "exec",
        ),
        {
            "_NativeUnavailable": NativeUnavailable,
            "_isfinite": math.isfinite,
        },
        namespace,
    )
    return namespace["_marshal"]


def _build_boundary_manifestation(
    operation: dict[str, Any],
) -> Any:
    judgements = ", ".join(
        (
            "{'expression': "
            + repr(expression)
            + ", 'passed': True}"
        )
        for expression in operation["judgements"]
    )
    restrictions = ", ".join(
        (
            "{'expression': "
            + repr(expression)
            + ", 'passed': True}"
        )
        for expression in operation["restrictions"]
    )
    stabilized = ", ".join(
        (
            "{'expression': "
            + repr(expression)
            + ", 'value': stabilized["
            + str(index)
            + " * records + record]}"
        )
        for index, expression in enumerate(operation["stabilized"])
    )
    state = "stable" if operation["stabilized"] else "partial"
    lines = [
        (
            "def _manifest(payloads, records, results, stabilized, "
            "artifact_id, module, operation_name):"
        ),
        "    items = [None] * records",
        "    for record in range(records):",
        "        items[record] = {",
        "            'artifact_id': artifact_id,",
        "            'module': module,",
        "            'operation': operation_name,",
        f"            'state': {state!r},",
        "            'input': dict(payloads[record]),",
        "            'result': results[record],",
        "            'evidence': {",
        f"                'judgements': [{judgements}],",
        f"                'restrictions': [{restrictions}],",
        "                'projections': [],",
        "                'bindings': [],",
        f"                'stabilized': [{stabilized}],",
        "            },",
        "            'cache': {",
        "                'enabled': False,",
        "                'hit': False,",
        "                'key': None,",
        "                'key_protocol': None,",
        "                'scope': None,",
        "                'collision_verified': False,",
        "            },",
        "        }",
        "    return items",
    ]
    namespace: dict[str, Any] = {}
    exec(
        compile(
            "\n".join(lines) + "\n",
            "<casulo-boundary-manifestation>",
            "exec",
        ),
        {},
        namespace,
    )
    return namespace["_manifest"]


def _load_prepared_executor(
    library_path: Path,
    manifest: dict[str, Any],
    operation: dict[str, Any],
) -> PreparedNativeExecutor:
    library = ctypes.CDLL(str(library_path))
    library.casulo_abi_version.restype = ctypes.c_uint32
    library.casulo_artifact_id.restype = ctypes.c_char_p
    if library.casulo_abi_version() != NATIVE_ABI_VERSION:
        raise NativeError("DLL expõe versão ABI incompatível")
    native_id = library.casulo_artifact_id().decode("ascii")
    if native_id != manifest["artifact_id"]:
        raise NativeError("DLL nativa pertence a outro artefato")
    execute = library.casulo_execute_f64
    execute.argtypes = [
        ctypes.c_uint32,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    execute.restype = ctypes.c_int32
    return PreparedNativeExecutor(
        library,
        execute,
        manifest,
        operation,
    )


def prepare_native_executor(
    artifact_dir: str | Path,
    operation: str | None = None,
    *,
    profile: str = "simd",
) -> tuple[
    PreparedNativeExecutor,
    dict[str, Any],
    dict[str, Any],
    NativeBuild,
]:
    """Prepara uma chamada persistente; útil para laboratório sem custo de load."""

    from .artifact import verify_artifact
    from .runner import select_operation

    directory, manifest = verify_artifact(artifact_dir)
    selected = select_operation(manifest, operation)
    native_entry = _native_operation(manifest, selected)
    if not native_entry.get("eligible"):
        raise NativeUnavailable(
            str(native_entry.get("reason") or "operação inelegível")
        )
    build = compile_native_artifact(directory, profile=profile)
    prepared = _load_prepared_executor(
        build.library,
        manifest,
        native_entry,
    )
    return prepared, manifest, native_entry, build


def _python_fallback(
    loaded: Any,
    operation: str,
    payloads: list[Any],
    is_batch: bool,
    reason: str,
) -> NativeRunResult:
    function = loaded.namespace["execute_batch"]
    try:
        batch_payload = function(operation, payloads, use_cache=False)
    except Exception as exc:
        raise NativeSemanticError(str(exc)) from exc
    payload = batch_payload if is_batch else batch_payload["items"][0]
    return NativeRunResult(
        artifact_dir=loaded.directory,
        artifact_id=loaded.manifest["artifact_id"],
        operation=operation,
        batch=is_batch,
        backend="python-fallback",
        fallback_reason=reason,
        native_build=None,
        payload=payload,
    )


def _native_operation(
    manifest: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    native = manifest.get("native")
    if not isinstance(native, dict):
        return {"name": name, "eligible": False, "reason": "backend C99 ausente"}
    for operation in native.get("operations", []):
        if operation.get("name") == name:
            return operation
    return {"name": name, "eligible": False, "reason": "operação ausente na ABI"}


def _runtime_incompatibility(
    payloads: list[Any],
    operation: dict[str, Any],
) -> str | None:
    if not operation.get("eligible"):
        return str(operation.get("reason") or "operação inelegível")
    fields = operation["input_fields"]
    expected = set(fields)
    for index, payload in enumerate(payloads):
        if type(payload) is not dict or set(payload) != expected:
            return f"registro {index}: esquema exato exigido pela ABI nativa"
        for field in fields:
            value = payload[field]
            if type(value) is not float or not math.isfinite(value):
                return (
                    f"registro {index}.{field}: ABI 0.1 exige float finito; "
                    "inteiros preservam semântica pelo fallback"
                )
    return None


def _remove_dead_lets(
    instructions: tuple[IRInstruction, ...],
) -> tuple[tuple[IRInstruction, ...], dict[str, Any]]:
    live: set[str] = set()
    kept: list[IRInstruction] = []
    removed = 0
    for instruction in reversed(instructions):
        expression_names = _expression_names(instruction.arguments[0])
        if instruction.op == "let" and instruction.result is not None:
            if instruction.result not in live:
                removed += 1
                continue
            live.discard(instruction.result)
        live.update(expression_names)
        kept.append(instruction)
    optimized = tuple(reversed(kept))
    return optimized, {
        "protocol": NATIVE_AOT_PROTOCOL,
        "instructions_before": len(instructions),
        "instructions_after": len(optimized),
        "dead_lets_removed": removed,
        "constants_propagated": 0,
        "aliases_propagated": 0,
    }


def _guard_phase_instructions(
    instructions: tuple[IRInstruction, ...],
) -> tuple[IRInstruction, ...]:
    """Conserva guardas e somente os lets dos quais elas dependem."""

    needed: set[str] = set()
    kept: list[IRInstruction] = []
    for instruction in reversed(instructions):
        if instruction.op in {"judge", "restrict"}:
            needed.update(_expression_names(instruction.arguments[0]))
            kept.append(instruction)
            continue
        if (
            instruction.op == "let"
            and instruction.result is not None
            and instruction.result in needed
        ):
            needed.discard(instruction.result)
            needed.update(_expression_names(instruction.arguments[0]))
            kept.append(instruction)
    return tuple(reversed(kept))


def _expression_names(text: str) -> set[str]:
    return expression_names(parse_expression(text))


def _constant_expression(
    node: ExpressionNode,
    constants: dict[str, float],
) -> float | None:
    value: float | int | bool
    if isinstance(node, LiteralNode) and isinstance(
        node.value,
        (bool, int, float),
    ):
        value = node.value
    elif isinstance(node, NameNode) and node.name in constants:
        return constants[node.name]
    elif isinstance(node, UnaryNode) and node.operator in {"+", "-"}:
        operand = _constant_expression(node.operand, constants)
        if operand is None:
            return None
        value = operand if node.operator == "+" else -operand
    elif isinstance(node, BinaryNode) and node.operator in {"+", "-", "*"}:
        left = _constant_expression(node.left, constants)
        right = _constant_expression(node.right, constants)
        if left is None or right is None:
            return None
        if node.operator == "+":
            value = left + right
        elif node.operator == "-":
            value = left - right
        else:
            value = left * right
    else:
        return None
    normalized = float(value)
    if not math.isfinite(normalized):
        return None
    if isinstance(value, int) and abs(value) > 2**53:
        return None
    return normalized


def _render_c_number(value: float) -> str:
    rendered = format(value, ".17g")
    if "." not in rendered and "e" not in rendered.lower():
        rendered += ".0"
    return rendered


def _ineligibility_reason(
    operation: IROperation,
    schema: dict[str, str] | None,
) -> str | None:
    if not schema or any(type_name != "Number" for type_name in schema.values()):
        return "entrada precisa ser um field não vazio composto apenas por Number"
    if operation.output_type != "Number":
        return "saída precisa ser Number"
    emit_count = sum(
        instruction.op == "emit" for instruction in operation.instructions
    )
    if emit_count != 1:
        return "backend C99 0.1 exige exatamente um emit"
    allowed = {"let", "judge", "restrict", "stabilize", "emit"}
    if any(instruction.op not in allowed for instruction in operation.instructions):
        return "backend C99 0.1 aceita somente fluxo numérico linear"
    names = set(schema)
    for instruction in operation.instructions:
        try:
            parsed = parse_expression(instruction.arguments[0])
            _validate_c_expression(parsed, names)
        except (ExpressionSyntaxError, NativeError) as exc:
            return f"expressão fora do subconjunto C99 seguro: {exc}"
        if instruction.op == "let" and instruction.result is not None:
            names.add(instruction.result)
    return None


def _validate_c_expression(node: ExpressionNode, names: set[str]) -> None:
    if isinstance(node, LiteralNode):
        if isinstance(node.value, (bool, int, float)):
            return
        raise NativeError("literal não numérico")
    if isinstance(node, NameNode):
        if node.name not in names:
            raise NativeError(f"nome desconhecido {node.name}")
        return
    if isinstance(node, UnaryNode) and node.operator in {"not", "+", "-"}:
        _validate_c_expression(node.operand, names)
        return
    if isinstance(node, BooleanNode) and node.operator in {"and", "or"}:
        for value in node.values:
            _validate_c_expression(value, names)
        return
    if isinstance(node, BinaryNode) and node.operator in {"+", "-", "*"}:
        _validate_c_expression(node.left, names)
        _validate_c_expression(node.right, names)
        return
    if isinstance(node, CompareNode):
        for value in node.values:
            _validate_c_expression(value, names)
        return
    raise NativeError(type(node).__name__)


def _render_c_expression(text: str, names: dict[str, str]) -> str:
    node = parse_expression(text)
    return _render_c_node(node, names)


def _render_c_node(node: ExpressionNode, names: dict[str, str]) -> str:
    if isinstance(node, LiteralNode):
        if isinstance(node.value, bool):
            return "1" if node.value else "0"
        if isinstance(node.value, int):
            return f"{node.value}.0"
        if isinstance(node.value, float):
            return repr(node.value)
    if isinstance(node, NameNode):
        return names[node.name]
    if isinstance(node, UnaryNode):
        operators = {"not": "!", "+": "+", "-": "-"}
        return f"({operators[node.operator]}{_render_c_node(node.operand, names)})"
    if isinstance(node, BooleanNode):
        operator = " && " if node.operator == "and" else " || "
        return "(" + operator.join(_render_c_node(item, names) for item in node.values) + ")"
    if isinstance(node, BinaryNode):
        return (
            f"({_render_c_node(node.left, names)} "
            f"{node.operator} {_render_c_node(node.right, names)})"
        )
    if isinstance(node, CompareNode):
        comparisons: list[str] = []
        left = node.values[0]
        for operator, right in zip(node.operators, node.values[1:]):
            comparisons.append(
                f"({_render_c_node(left, names)} {operator} "
                f"{_render_c_node(right, names)})"
            )
            left = right
        return "(" + " && ".join(comparisons) + ")"
    raise NativeError(f"expressão C99 não renderizável: {type(node).__name__}")


def _find_compiler() -> Path:
    names = (
        ("gcc", "clang")
        if os.name != "nt"
        else ("gcc.exe", "clang.exe", "clang-cl.exe", "cl.exe")
    )
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    raise NativeUnavailable(
        "nenhum compilador C encontrado; instale GCC, Clang ou MSVC"
    )


def _compiler_version(compiler: Path) -> str:
    command = (
        [str(compiler), "--version"]
        if compiler.name.lower() != "cl.exe"
        else [str(compiler)]
    )
    process = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
    )
    output = (process.stdout or process.stderr).strip().splitlines()
    if not output:
        raise NativeUnavailable(f"não foi possível identificar {compiler}")
    return output[0].strip()


def _compile_command(
    compiler: Path,
    source: Path,
    output: Path,
    *,
    profile: str,
    vector_report: Path,
) -> list[str]:
    name = compiler.name.lower()
    if name == "cl.exe" or name == "clang-cl.exe":
        command = [
            str(compiler),
            "/nologo",
            "/O2",
            "/LD",
            "/std:c11",
            "/Brepro",
            "/fp:strict",
        ]
        if profile == "simd":
            command.append("/arch:AVX2")
        elif name == "clang-cl.exe":
            command.extend(
                [
                    "/clang:-fno-vectorize",
                    "/clang:-fno-slp-vectorize",
                ]
            )
        command.extend(
            [
            str(source),
            f"/Fe:{output}",
            ]
        )
        return command
    command = [
        str(compiler),
        "-std=c99",
        "-O3",
        "-fno-fast-math",
        "-ffp-contract=off",
        "-shared",
    ]
    if profile == "simd":
        command.append("-march=native")
        if "gcc" in name:
            command.extend(
                [
                    "-ftree-vectorize",
                    f"-fopt-info-vec-all={vector_report}",
                ]
            )
        else:
            command.append("-Rpass=loop-vectorize")
    elif "gcc" in name:
        command.append("-fno-tree-vectorize")
    else:
        command.extend(["-fno-vectorize", "-fno-slp-vectorize"])
    if os.name != "nt":
        command.extend(["-fPIC", "-fvisibility=hidden"])
    else:
        command.extend(
            [
                "-Wl,--no-insert-timestamp,--image-base,0x180000000",
                "-s",
            ]
        )
    command.extend([str(source), "-o", str(output)])
    return command


def _portable_command(
    command: list[str],
    source: Path,
    output: Path,
    vector_report: Path,
) -> list[str]:
    replacements = {
        str(source): "$CASULO_ARTIFACT/" + NATIVE_SOURCE_FILE,
        str(output): "$CASULO_NATIVE_OUTPUT",
        f"/Fe:{output}": "/Fe:$CASULO_NATIVE_OUTPUT",
        f"-fopt-info-vec-all={vector_report}": (
            "-fopt-info-vec-all=$CASULO_VECTOR_REPORT"
        ),
    }
    return [replacements.get(str(item), str(item)) for item in command]


def _native_target(profile: str) -> str:
    if profile == "scalar":
        return "portable-scalar"
    identity = (
        platform.machine()
        + "|"
        + platform.processor()
        + "|"
        + os.environ.get("PROCESSOR_IDENTIFIER", "")
    )
    return "host-simd:" + _sha256(identity.encode("utf-8"))[:16]


def _vectorization_report(
    path: Path,
    stdout: str,
    stderr: str,
    source: Path,
) -> tuple[str, ...]:
    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        combined = (stdout + "\n" + stderr).splitlines()
        lines = [
            line
            for line in combined
            if "vectorized" in line.lower()
            or "loop-vectorize" in line.lower()
        ]
    portable_source = "$CASULO_ARTIFACT/" + NATIVE_SOURCE_FILE
    return tuple(
        line.strip().replace(str(source), portable_source)
        for line in lines
        if line.strip()
    )


def _platform_tag() -> str:
    return "-".join(
        (
            platform.system().lower(),
            platform.machine().lower() or "unknown",
        )
    )


def _native_cache_root() -> Path:
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA", tempfile.gettempdir())
        ).resolve()
        return base / "Casulo" / "native-cache"
    base = Path(
        os.environ.get(
            "XDG_CACHE_HOME",
            str(Path.home() / ".cache"),
        )
    ).expanduser().resolve()
    return base / "casulo" / "native-cache"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
