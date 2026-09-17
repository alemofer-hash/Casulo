from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "paper_artifacts"
DIST = ART / "dist"
ZIP_NAME = "GUILHERME_MOURA_FERNANDES_T_LANGUAGE_PAPER_EVIDENCE.zip"
PACKAGE_ROOT = "GUILHERME_MOURA_FERNANDES_T_LANGUAGE_PAPER_EVIDENCE"
FIXED_ZIP_TIME = (2026, 8, 7, 12, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path, *, include_suffixes: set[str] | None = None) -> None:
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        if include_suffixes is not None and path.suffix.lower() not in include_suffixes:
            continue
        copy_file(path, dst / path.relative_to(src))


def command(*args: str) -> str:
    return subprocess.run(
        list(args), cwd=ROOT, check=True, text=True, encoding="utf-8",
        errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ).stdout.strip()


def environment_snapshot() -> dict[str, object]:
    versions: dict[str, object] = {"python": sys.version.split()[0]}
    for module_name in ("numpy", "torch"):
        try:
            module = __import__(module_name)
            versions[module_name] = getattr(module, "__version__", "unknown")
        except Exception as exc:
            versions[module_name] = {"unavailable": type(exc).__name__}
    cpu = os.environ.get("PROCESSOR_IDENTIFIER", "unknown")
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_commit": command("git", "rev-parse", "HEAD"),
        "repository_branch": command("git", "branch", "--show-current"),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "processor_environment": cpu,
        "logical_cpu_count": os.cpu_count(),
        "versions": versions,
        "performance_rerun": {
            "status": "NOT_RUN_THERMAL_TELEMETRY_UNAVAILABLE",
            "reason": "No fresh advancing HWiNFO telemetry was available during packaging.",
        },
        "energy": {
            "electrical_energy_measured": False,
            "joules": None,
        },
    }


def write_integrity(package: Path) -> None:
    integrity = package / "08_INTEGRITY"
    integrity.mkdir(parents=True, exist_ok=True)
    payload_files = sorted(
        path for path in package.rglob("*")
        if path.is_file() and path.parent != integrity
    )
    entries = [
        {
            "path": path.relative_to(package).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in payload_files
    ]
    manifest = {
        "schema": "casulo-t-paper-evidence-manifest/1.0",
        "author": "Guilherme Moura Fernandes",
        "title_pt": "A Linguagem T como otimização do gerenciamento do uso da CPU durante treinamento de Redes Neurais Artificiais",
        "integrity_scope": "All package files except 08_INTEGRITY itself",
        "file_count": len(entries),
        "files": entries,
    }
    (integrity / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (integrity / "SHA256SUMS").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in entries),
        encoding="utf-8",
    )


def create_zip(package: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(PACKAGE_ROOT) / path.relative_to(package)
            info = zipfile.ZipInfo(relative.as_posix(), FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def main() -> int:
    subprocess.run([sys.executable, str(ART / "scripts/analyze_results.py")], cwd=ROOT, check=True)
    DIST.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="casulo-paper-") as temporary:
        package = Path(temporary) / PACKAGE_ROOT
        copy_file(ART / "PACKAGE_README.md", package / "README.md")

        for name in ("repository_architecture.md", "semantic_execution_chain.md", "implementation_map.csv"):
            copy_file(ART / "source_docs" / name, package / "01_ARCHITECTURE" / name)
        for name in ("experimental_protocol.md", "claims_evidence_matrix.csv", "profiling_and_energy.md", "glossary_4_languages.csv"):
            copy_file(ART / "source_docs" / name, package / "02_PROTOCOL" / name)

        raw = package / "03_EVIDENCE" / "RAW"
        raw_sources = {
            ROOT / "evidence/2026-07-30-marco4-6x": raw / "waterbalance_historical",
            ROOT / "benchmarks/results/2026-07-30-scientific-covenant-eager": raw / "training_pytorch_eager_historical",
            ROOT / "benchmarks/results/2026-07-30-scientific-covenant-compile": raw / "training_pytorch_inductor_historical",
            ROOT / "benchmarks/results/2026-08-02-sprint025-ablation": raw / "thermal_attempt_blocked_before_start",
        }
        for src, dst in raw_sources.items():
            copy_tree(src, dst)
        copy_tree(ART / "generated/benchmarks", package / "03_EVIDENCE/PROCESSED")
        copy_tree(ROOT / "benchmarks/results/2026-07-30-sprint024-causal", package / "03_EVIDENCE/PROFILES")

        implementation_files = [
            "src/casulo/t/lexer.py", "src/casulo/t/parser.py", "src/casulo/t/ast.py",
            "src/casulo/t/analyzer.py", "src/casulo/t/typesys.py", "src/casulo/t/symbols.py",
            "src/casulo/t/ir.py", "src/casulo/t/graph.py", "src/casulo/t/artifact.py",
            "src/casulo/t/backend.py", "src/casulo/t/native.py", "src/casulo/t/tensor.py",
            "src/casulo/t/autograd.py", "src/casulo/t/linear_algebra.py",
            "src/casulo/t/tensor_cpu.py", "src/casulo/t/parity.py", "src/casulo/t/training.py",
            "src/casulo/t/tensor_lab.py", "src/casulo/t/scientific.py", "src/casulo/t/thermal.py",
            "src/casulo/t/thermal_watchdog.py", "pyproject.toml",
        ]
        for relative in implementation_files:
            copy_file(ROOT / relative, package / "04_IMPLEMENTATION" / relative)
        for doc in (
            "t-spec-1.0.md", "workspace-0.1.md", "crisalida-ir-0.1.md",
            "metamorfose-graph-0.1.md", "native-abi-0.1.md", "tensor-abi-0.1.md",
            "autograd-0.1.md", "tensor-cpu-backend-0.1.md", "linear-algebra-0.1.md",
            "training-benchmark-0.1.md", "scientific-covenant-1.0.md",
        ):
            copy_file(ROOT / "docs" / doc, package / "04_IMPLEMENTATION/docs" / doc)

        copy_tree(ART / "literature", package / "05_LITERATURE")
        copy_tree(ART / "manuscripts", package / "06_MANUSCRIPTS", include_suffixes={".tex", ".bib", ".pdf"})
        copy_file(ART / "generated/tests/correctness-junit.xml", package / "07_TESTS/correctness-junit.xml")
        (package / "07_TESTS/README.md").write_text(
            "33 tests and 42 subtests passed in 14.33 s with one thread; this is a correction gate, not a performance benchmark.\n",
            encoding="utf-8",
        )

        integrity = package / "08_INTEGRITY"
        integrity.mkdir(parents=True, exist_ok=True)
        (integrity / "environment.json").write_text(
            json.dumps(environment_snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (integrity / "repository_state.txt").write_text(
            "commit=" + command("git", "rev-parse", "HEAD") + "\n"
            + "branch=" + command("git", "branch", "--show-current") + "\n"
            + "tracked_diff_name_status=\n" + command("git", "diff", "--name-status") + "\n"
            + "status_short=\n" + command("git", "status", "--short") + "\n",
            encoding="utf-8",
        )
        copy_file(ART / "scripts/analyze_results.py", package / "SCRIPTS/analyze_results.py")
        copy_file(ART / "scripts/verify_package.py", package / "SCRIPTS/verify_package.py")
        write_integrity(package)

        zip_path = DIST / ZIP_NAME
        create_zip(package, zip_path)
        copy_file(ART / "PROMPT_GPT_GERAR_4_PAPERS.md", DIST / "PROMPT_GPT_GERAR_4_PAPERS.md")
        (DIST / f"{ZIP_NAME}.sha256").write_text(f"{sha256(zip_path)}  {ZIP_NAME}\n", encoding="ascii")
        print(json.dumps({"status": "OK", "zip": str(zip_path), "bytes": zip_path.stat().st_size, "sha256": sha256(zip_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
