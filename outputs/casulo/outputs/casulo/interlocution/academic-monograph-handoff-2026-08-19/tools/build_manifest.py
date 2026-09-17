from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"MANIFEST.json", "SHA256SUMS"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


files = []
for path in sorted(p for p in ROOT.rglob("*") if p.is_file()):
    rel = path.relative_to(ROOT).as_posix()
    if rel in EXCLUDED or rel.endswith(".zip"):
        continue
    files.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path)})

manifest = {
    "schema": "casulo.academic-monograph-handoff/1.0",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "author": "Guilherme Moura Fernandes",
    "title": (
        "Princípio da Interlocução: a Linguagem T como arquiteta, auditora e "
        "juíza da integridade semântica em modelos de treinamento de redes "
        "neurais artificiais e a decorrente compressão física da informação preservada"
    ),
    "page_target": 185,
    "page_range": [170, 200],
    "file_count": len(files),
    "total_bytes": sum(item["bytes"] for item in files),
    "files": files,
}

(ROOT / "MANIFEST.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(ROOT / "SHA256SUMS").write_text(
    "".join(f'{item["sha256"]}  {item["path"]}\n' for item in files),
    encoding="utf-8",
)
print(json.dumps({"files": len(files), "bytes": manifest["total_bytes"]}))
