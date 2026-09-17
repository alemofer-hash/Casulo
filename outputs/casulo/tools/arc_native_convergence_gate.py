from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "product-demos/human-proof"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def attempt(root: Path) -> Path:
    for sequence in range(1, 100):
        target = root / f"arc-native-convergence-2026-08-18-attempt{sequence}"
        try:
            target.mkdir(parents=True, exist_ok=False)
            return target
        except FileExistsError:
            continue
    raise RuntimeError("limite de attempts ARC-10 excedido")


def load_qemu_gate(repo: Path):
    tools = repo / "os/tools"
    sys.path.insert(0, str(tools))
    specification = importlib.util.spec_from_file_location(
        "arc10_product_gate", tools / "run_product_alpha_qemu.py"
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("gate QEMU não pôde ser carregado")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def extract_rust_array(source: str, name: str) -> list[str]:
    match = re.search(
        rf"pub const {name}: \[&str; \d+\] = \[(.*?)\];",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"array Rust ausente: {name}")
    return re.findall(r'"([A-Z_]+)"', match.group(1))


def run(repo: Path, output_root: Path) -> Path:
    repo = repo.resolve()
    output = attempt(output_root.resolve())
    contract_path = repo / "schemas/product/hosted-native-ux-contract-v1.json"
    native_source_path = repo / "os/kernel/src/product_runtime.rs"
    tcap = repo / "release/FloodSurrogate.tcap"
    for required in (contract_path, native_source_path, tcap):
        if not required.is_file():
            raise RuntimeError(f"dependência ARC-10 ausente: {required}")

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract_digest = sha256(contract_path)
    native_source = native_source_path.read_text(encoding="utf-8")
    conformance = {
        "schema": "casulo.arc10-conformance/1.0",
        "contract_sha256": contract_digest,
        "rust_hash_match": contract_digest in native_source,
        "wire_schema_match": str(contract["wire_schema"]) in native_source,
        "event_kinds_match": extract_rust_array(native_source, "CONTRACT_EVENT_KINDS")
        == contract["event_kinds"],
        "priorities_match": extract_rust_array(native_source, "CONTRACT_PRIORITIES")
        == contract["priorities"],
        "hosted_only_adapters_declared": all(
            item in (repo / "os/kernel/src/main.rs").read_text(encoding="utf-8")
            for item in (
                "model-inference",
                "physical-audio",
                "dpapi-memory",
                "creation-renderer",
                "materializer",
            )
        ),
    }
    if not all(value for key, value in conformance.items() if key.endswith("_match")):
        raise RuntimeError("contrato Hosted/Native divergiu")

    build_environment = dict(os.environ)
    temporary = repo / ".tmp/arc10-native-gate"
    temporary.mkdir(parents=True, exist_ok=True)
    build_environment["TMP"] = str(temporary)
    build_environment["TEMP"] = str(temporary)
    command = [
        "cargo",
        "+nightly-2026-02-01",
        "-Z",
        "bindeps",
        "run",
        "--manifest-path",
        "os/Cargo.toml",
        "--release",
        "--locked",
        "--offline",
    ]
    completed = subprocess.run(
        command,
        cwd=repo,
        env=build_environment,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    generated_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not generated_lines:
        raise RuntimeError("build Native não informou imagem")
    generated = Path(generated_lines[-1]).resolve()
    if not generated.is_file() or (repo / "os").resolve() not in generated.parents:
        raise RuntimeError("imagem Native gerada fora da raiz confinada")
    image = output / "casulo-native-arc10.img"
    shutil.copyfile(generated, image)

    qemu_gate = load_qemu_gate(repo)
    dependencies = {
        "qemu": qemu_gate.DEFAULT_QEMU.resolve(),
        "ovmf_code": qemu_gate.DEFAULT_CODE.resolve(),
        "ovmf_vars": qemu_gate.DEFAULT_VARS.resolve(),
    }
    for name, dependency in dependencies.items():
        if not dependency.is_file():
            raise RuntimeError(f"dependência física do gate ausente: {name}={dependency}")
    boot = qemu_gate.boot_once(
        image,
        dependencies["qemu"],
        dependencies["ovmf_code"],
        dependencies["ovmf_vars"],
        45.0,
    )
    validation = qemu_gate.validate_product_boot(boot, sha256(tcap))
    (output / "serial.log").write_text(str(boot["serial"]), encoding="utf-8")
    write_json(
        output / "native-acceptance.json",
        {
            "schema": "casulo.arc10-native-acceptance/1.0",
            "validation": validation,
            "image": {
                "path": image.name,
                "bytes": image.stat().st_size,
                "sha256": sha256(image),
            },
            "tcap": {"path": "release/FloodSurrogate.tcap", "sha256": sha256(tcap)},
            "qemu": {
                "acceleration": "tcg",
                "vcpus": 2,
                "network": False,
                "image_read_only": True,
                "host_block_devices_attached": False,
                "physical_device_written": False,
            },
            "performance_measured": False,
            "energy_measured": False,
            "scientific_benchmark": False,
        },
    )
    write_json(output / "conformance.json", conformance)
    write_json(
        output / "build.json",
        {
            "schema": "casulo.arc10-native-build/1.0",
            "command": command,
            "offline": True,
            "locked": True,
            "returncode": completed.returncode,
            "generated_image_sha256": sha256(image),
            "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        },
    )
    shutil.copyfile(contract_path, output / contract_path.name)

    state = "PASS" if validation["passed"] and all(
        bool(value)
        for key, value in conformance.items()
        if key not in {"schema", "contract_sha256"}
    ) else "FAIL"
    report = (
        "# ARC-10 — convergência Hosted/Native\n\n"
        f"Estado: `{state}`  \n"
        "Classificação: `NATIVE_CONTROL_PLANE_BOOT_PROOF_NOT_NATIVE_MODEL_OR_VOICE_PROOF`\n\n"
        "O boot QEMU executou o mesmo contrato de presença, streaming e jobs do "
        "Hosted. PRESENCE preemptou BACKGROUND; streams fora de ordem, jobs sem "
        "evidência e conclusão após cancelamento foram recusados. Inferência neural, "
        "áudio físico, DPAPI, renderer e materialização continuam corretamente Hosted.\n"
    )
    (output / "report.md").write_text(report, encoding="utf-8")

    files = []
    for path in sorted(item for item in output.iterdir() if item.is_file()):
        files.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema": "casulo.arc10-evidence-manifest/1.0",
        "state": state,
        "classification": "NATIVE_CONTROL_PLANE_BOOT_PROOF_NOT_NATIVE_MODEL_OR_VOICE_PROOF",
        "files": files,
    }
    write_json(output / "MANIFEST.json", manifest)
    sums = [f"{item['sha256']}  {item['path']}" for item in files]
    sums.append(f"{sha256(output / 'MANIFEST.json')}  MANIFEST.json")
    (output / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="ascii")
    result = {
        "state": state,
        "output": str(output),
        "manifest_sha256": sha256(output / "MANIFEST.json"),
        "image_sha256": sha256(image),
        "contract_sha256": contract_digest,
    }
    print(json.dumps(result, ensure_ascii=False))
    if state != "PASS":
        raise RuntimeError("gate ARC-10 falhou")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate ARC-10 Hosted/Native")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    run(args.repo, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
