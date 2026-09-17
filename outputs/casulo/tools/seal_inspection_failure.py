from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(root: Path) -> None:
    evidence_roots = [root / "owner-data", root / "state"]
    files = sorted(
        (path for base in evidence_roots for path in base.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    items = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": sha256(path),
        }
        for path in files
    ]
    inventory = {
        "schema": "casulo.inspection-failure-inventory/1.0",
        "failure": "KeyError: name after run_probe",
        "preservation": "COPY_ONLY_SOURCE_UNMODIFIED",
        "file_count": len(items),
        "total_bytes": sum(item["bytes"] for item in items),
        "files": items,
    }
    inventory_path = root / "FORENSIC_INVENTORY.json"
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report = """# Terceira falha de inspeção — preservação forense

Estado: `IN_PROGRESS_CHECKPOINTED`

O `run_probe` concluiu geração T, quatro reparos baseados em diagnostics, compilação,
simulação sem efeitos reais, materialização, importação/round-trip e publicação da
sessão Semantic Multiverse. A exceção ocorreu somente na projeção visual posterior.

`content.identity.name` é opcional no contrato `casulo.creation/1.0`; somente
`creation_id` é identidade obrigatória. O renderer possuía um contrato mais estreito
e não declarado ao acessar o dicionário cru.

O artefato preservado **não é um solver de Einstein**. Ele é um agente T genérico
de leitura de memória cujo texto/metadata contém a intenção científica. Não há no
código materializado construção de conexão de Levi-Civita, Ricci, escalar de Ricci,
tensor de Einstein ou resíduos.

Nenhum arquivo sob `owner-data/` ou `state/` foi regenerado, sobrescrito ou apagado.
"""
    (root / "FORENSIC_REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    sealed = [*files, inventory_path, root / "FORENSIC_REPORT.md"]
    sums = "".join(
        f"{sha256(path)}  {path.relative_to(root).as_posix()}\n"
        for path in sorted(sealed, key=lambda item: item.relative_to(root).as_posix())
    )
    (root / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    main(args.root.resolve(strict=True))
