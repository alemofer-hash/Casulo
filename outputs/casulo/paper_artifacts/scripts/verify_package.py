from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "paper_artifacts/dist"
ZIP_NAME = "GUILHERME_MOURA_FERNANDES_T_LANGUAGE_PAPER_EVIDENCE.zip"
PACKAGE_ROOT = "GUILHERME_MOURA_FERNANDES_T_LANGUAGE_PAPER_EVIDENCE"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    archive_path = DIST / ZIP_NAME
    prompt_path = DIST / "PROMPT_GPT_GERAR_4_PAPERS.md"
    if not archive_path.is_file() or not prompt_path.is_file():
        raise SystemExit("missing required deliverable")
    with tempfile.TemporaryDirectory(prefix="verify-casulo-paper-") as temporary:
        with zipfile.ZipFile(archive_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise SystemExit(f"corrupt zip member: {bad_member}")
            archive.extractall(temporary)
        package = Path(temporary) / PACKAGE_ROOT
        manifest = json.loads((package / "08_INTEGRITY/MANIFEST.json").read_text(encoding="utf-8"))
        failures = []
        for entry in manifest["files"]:
            path = package / entry["path"]
            actual = sha256(path) if path.is_file() else None
            if actual != entry["sha256"] or (path.is_file() and path.stat().st_size != entry["bytes"]):
                failures.append(entry["path"])
        expected_titles = {
            "pt": "A Linguagem T como otimização do gerenciamento do uso da CPU durante treinamento de Redes Neurais Artificiais",
            "en": "The T Language as an Optimization of CPU Usage Management During Artificial Neural Network Training",
            "es": "El lenguaje T como optimización de la gestión del uso de la CPU durante el entrenamiento de redes neuronales artificiales",
            "fr": "Le langage T comme optimisation de la gestion de l'utilisation du processeur pendant l'entraînement de réseaux de neurones artificiels",
        }
        title_failures = []
        for language, title in expected_titles.items():
            text = (package / f"06_MANUSCRIPTS/{language}/main.tex").read_text(encoding="utf-8")
            if title not in text or "Guilherme Moura Fernandes" not in text:
                title_failures.append(language)
        pdfs = [package / f"06_MANUSCRIPTS/{lang}/main.pdf" for lang in expected_titles]
        result = {
            "status": "PASS" if not failures and not title_failures and all(p.is_file() for p in pdfs) else "FAIL",
            "archive_sha256": sha256(archive_path),
            "manifest_entries_checked": len(manifest["files"]),
            "hash_failures": failures,
            "title_or_author_failures": title_failures,
            "compiled_pdfs_present": all(p.is_file() for p in pdfs),
            "prompt_present_beside_zip": prompt_path.is_file(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
