from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .authority import canonical_bytes, canonical_sha256
from .v2_ir import lower_module
from .v2_parser import V2Parser
from .v2_semantics import V2Analyzer


TCAP_V2 = "casulo.tcap/2.0"
SECTIONS = {
    "header":"header.json","module_graph":"module-graph.json","typed_ir":"typed-ir.json",
    "functional_code":"code.json","readonly_data":"readonly-data.json","effects":"effects.json",
    "capabilities":"capabilities.json","resource_budgets":"resource-budgets.json","schemas":"schemas.json",
    "source_map":"source-map.json","tests":"tests.json","foreign_boundaries":"foreign-boundaries.json",
    "provenance":"provenance.json","signature_class":"signature-class.json",
}


class TcapV2Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TcapV2Build:
    directory: Path
    tcap_hash: str
    manifest: dict[str, Any]


def _pretty(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


class TcapV2Builder:
    def build(self, sources: Iterable[str | Path], output: str | Path, *, entry_module: str, entry_function: str, tests: Mapping[str, Any] | None = None, foreign_boundaries: Iterable[Mapping[str, Any]] = ()) -> TcapV2Build:
        source_paths = tuple(Path(item).resolve() for item in sources)
        modules = []
        source_entries = []
        for path in source_paths:
            source_bytes = path.read_bytes()
            try:
                source = source_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise TcapV2Error(f"source T não é UTF-8: {path}") from exc
            module = V2Parser().parse(source, path.as_posix())
            analysis = V2Analyzer().analyze(module)
            if not analysis.ok: raise TcapV2Error("; ".join(f"{item.code}:{item.message}" for item in analysis.diagnostics))
            modules.append(module)
            source_entries.append({"module":module.name,"sha256":hashlib.sha256(source_bytes).hexdigest(),"file":f"sources/{module.name}.t"})
        names = {item.name for item in modules}
        if len(names) != len(modules) or entry_module not in names: raise TcapV2Error("module graph inválido")
        for module in modules:
            missing=set(module.imports)-names
            if missing: raise TcapV2Error(f"imports ausentes em {module.name}: {sorted(missing)}")
        primary = next(item for item in modules if item.name == entry_module)
        if entry_function not in {item.name for item in primary.functions}: raise TcapV2Error("entry function ausente")
        irs=[lower_module(item).payload for item in modules]
        graph={"schema":"casulo.t-module-graph/2.0","entry":{"module":entry_module,"function":entry_function},"modules":[{"name":item.name,"imports":list(item.imports)} for item in modules]}
        sections: dict[str,Any] = {
            "header":{"schema":TCAP_V2,"target":"portable-t-vm","verified_before_execution":True},
            "module_graph":graph,"typed_ir":{"schema":"casulo.t-ir-bundle/2.0","modules":irs},
            "functional_code":{"schema":"casulo.t-bytecode/2.0","encoding":"structured-opcodes","entry":graph["entry"],"modules":[{"name":ir["module"],"functions":ir["functions"]} for ir in irs]},
            "readonly_data":{"states":{ir["module"]:ir["states"] for ir in irs}},
            "effects":{"modules":{ir["module"]:{fn["name"]:fn["effects"] for fn in ir["functions"]} for ir in irs}},
            "capabilities":{"modules":{ir["module"]:ir["capabilities"] for ir in irs}},
            "resource_budgets":{"modules":{ir["module"]:ir["budgets"] for ir in irs}},
            "schemas":{"modules":{ir["module"]:{"version":ir["schema_version"],"records":ir["records"],"enums":ir["enums"]} for ir in irs}},
            "source_map":{"sources":source_entries},"tests":dict(tests or {"properties":[]}),
            "foreign_boundaries":{"items":[dict(item) for item in foreign_boundaries]},
            "provenance":{"sources":source_entries,"compiler":"T/2.0","builder":"casulo-python-tooling"},
            "signature_class":{"value":"DEVELOPMENT_NOT_COMMERCIAL"},
        }
        section_bytes={SECTIONS[name]:_pretty(value) for name,value in sections.items()}
        section_manifest={name:{"file":SECTIONS[name],"sha256":hashlib.sha256(section_bytes[SECTIONS[name]]).hexdigest()} for name in SECTIONS}
        seed={"schema":TCAP_V2,"sections":section_manifest,"sources":source_entries}
        tcap_hash=canonical_sha256(seed)
        manifest={"schema":TCAP_V2,"tcap_hash":tcap_hash,"entry":graph["entry"],"sections":section_manifest,"sources":source_entries}
        target=Path(output).resolve()
        if target.exists(): raise TcapV2Error(f"destino já existe: {target}")
        target.parent.mkdir(parents=True,exist_ok=True);temporary=Path(tempfile.mkdtemp(prefix=f".{target.name}.",dir=target.parent))
        try:
            for filename,content in section_bytes.items():(temporary/filename).write_bytes(content)
            (temporary/"sources").mkdir()
            for path,module in zip(source_paths,modules,strict=True):(temporary/f"sources/{module.name}.t").write_bytes(path.read_bytes())
            (temporary/"MANIFEST.json").write_bytes(_pretty(manifest));temporary.rename(target)
        except BaseException:
            if temporary.exists():shutil.rmtree(temporary)
            raise
        return TcapV2Build(target,tcap_hash,manifest)


def verify_tcap_v2(path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root=Path(path).resolve()
    try:manifest=json.loads((root/"MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError,UnicodeError) as exc:raise TcapV2Error("manifest TCAP v2 inválido") from exc
    if manifest.get("schema")!=TCAP_V2 or set(manifest.get("sections",{}))!=set(SECTIONS):raise TcapV2Error("seções TCAP v2 incompletas")
    for name,entry in manifest["sections"].items():
        file=(root/entry["file"]).resolve()
        if not file.is_relative_to(root) or not file.is_file():raise TcapV2Error(f"seção ausente ou externa: {name}")
        if hashlib.sha256(file.read_bytes()).hexdigest()!=entry["sha256"]:raise TcapV2Error(f"hash inválido: {name}")
    for source in manifest.get("sources",[]):
        file=(root/source["file"]).resolve()
        if not file.is_relative_to(root) or hashlib.sha256(file.read_bytes()).hexdigest()!=source["sha256"]:raise TcapV2Error("source inválida")
    seed={"schema":TCAP_V2,"sections":manifest["sections"],"sources":manifest["sources"]}
    if canonical_sha256(seed)!=manifest.get("tcap_hash"):raise TcapV2Error("identidade TCAP v2 inválida")
    loaded: dict[str, Any] = {}
    for name, entry in manifest["sections"].items():
        try:
            loaded[name] = json.loads((root / entry["file"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise TcapV2Error(f"seção JSON inválida: {name}") from exc
    header = loaded["header"]
    graph = loaded["module_graph"]
    typed = loaded["typed_ir"]
    code = loaded["functional_code"]
    if header != {"schema": TCAP_V2, "target": "portable-t-vm", "verified_before_execution": True}:
        raise TcapV2Error("header TCAP v2 inválido")
    if graph.get("schema") != "casulo.t-module-graph/2.0" or graph.get("entry") != manifest.get("entry"):
        raise TcapV2Error("module graph TCAP v2 inválido")
    if typed.get("schema") != "casulo.t-ir-bundle/2.0" or not isinstance(typed.get("modules"), list):
        raise TcapV2Error("typed IR TCAP v2 inválido")

    # A valid hash is not enough: the verifier rebuilds the typed IR from the
    # preserved T source and rejects a capsule whose source and executable
    # semantics disagree, even when an attacker recomputes every manifest hash.
    rebuilt_modules = []
    for source in manifest.get("sources", []):
        source_path = (root / source["file"]).resolve()
        try:
            module = V2Parser().parse(source_path.read_text(encoding="utf-8"), source_path.as_posix())
            analysis = V2Analyzer().analyze(module)
        except (OSError, UnicodeError, ValueError) as exc:
            raise TcapV2Error("source T não recompilável") from exc
        if not analysis.ok:
            raise TcapV2Error("source T semanticamente inválida")
        if module.name != source.get("module"):
            raise TcapV2Error("identidade de módulo diverge da source")
        rebuilt_modules.append(lower_module(module).payload)
    if typed["modules"] != rebuilt_modules:
        raise TcapV2Error("typed IR diverge da source T")
    expected_graph = {
        "schema": "casulo.t-module-graph/2.0",
        "entry": manifest["entry"],
        "modules": [
            {"name": item["module"], "imports": item["imports"]}
            for item in rebuilt_modules
        ],
    }
    if graph != expected_graph:
        raise TcapV2Error("module graph diverge da source T")
    expected_code = {
        "schema": "casulo.t-bytecode/2.0",
        "encoding": "structured-opcodes",
        "entry": manifest["entry"],
        "modules": [
            {"name": item["module"], "functions": item["functions"]}
            for item in rebuilt_modules
        ],
    }
    if code != expected_code:
        raise TcapV2Error("bytecode funcional diverge do typed IR")
    entry_module = next(
        (item for item in rebuilt_modules if item["module"] == manifest["entry"].get("module")),
        None,
    )
    if entry_module is None or manifest["entry"].get("function") not in {
        item["name"] for item in entry_module["functions"]
    }:
        raise TcapV2Error("entrypoint TCAP v2 ausente")
    return root,manifest,typed


def build_native_probe_bundle(
    tcap: str | Path,
    output: str | Path,
    *,
    function_name: str,
    payload: Mapping[str, Any],
    grants: Iterable[str],
    surface_id: str,
    scope_id: str,
    previous_receipt_hash: str = "0" * 64,
) -> Path:
    """Seal one TCAP v2 execution request as a single Native ramdisk.

    The bundle contains sources and section bytes, never a precomputed result.
    Native must verify, interpret and emit the observable itself.
    """
    root, manifest, _typed = verify_tcap_v2(tcap)
    sections = {
        name: {
            "file": entry["file"],
            "sha256": entry["sha256"],
            "content_utf8": (root / entry["file"]).read_text(encoding="utf-8"),
        }
        for name, entry in manifest["sections"].items()
    }
    sources = [
        {
            **entry,
            "content_utf8": (root / entry["file"]).read_text(encoding="utf-8"),
        }
        for entry in manifest["sources"]
    ]
    request = {
        "function": function_name,
        "payload": dict(payload),
        "grants": sorted(set(grants)),
        "surface_id": surface_id,
        "scope_id": scope_id,
        "previous_receipt_hash": previous_receipt_hash,
    }
    bundle_seed = {
        "schema": "casulo.native-t-v2-probe/1.0",
        "manifest": manifest,
        "sections": sections,
        "sources": sources,
        "request": request,
    }
    bundle = {**bundle_seed, "bundle_sha256": canonical_sha256(bundle_seed)}
    target = Path(output).resolve()
    if target.exists():
        raise TcapV2Error(f"destino já existe: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_pretty(bundle))
    return target
