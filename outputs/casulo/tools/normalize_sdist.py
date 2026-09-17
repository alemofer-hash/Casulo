"""Normaliza um sdist tar.gz para reprodução byte a byte.

Setuptools ainda pode gravar o horário do build em diretórios e metadados tar.
Este utilitário conserva nomes, conteúdo, links e permissões, mas fixa autoria,
mtime, PAX e cabeçalho gzip a SOURCE_DATE_EPOCH.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import os
import tarfile
import tempfile
from pathlib import Path


def normalize_sdist(path: str | Path, epoch: int) -> Path:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or not source.name.endswith(".tar.gz"):
        raise ValueError(f"sdist inválido: {source}")
    if epoch < 0:
        raise ValueError("epoch precisa ser não negativo")

    with tarfile.open(source, "r:gz") as archive:
        entries = []
        for member in archive.getmembers():
            extracted = archive.extractfile(member) if member.isfile() else None
            entries.append((copy.copy(member), extracted.read() if extracted else None))

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{source.name}.",
        suffix=".normalized",
        dir=source.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=epoch,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as output:
                    for member, content in entries:
                        member.mtime = epoch
                        member.uid = 0
                        member.gid = 0
                        member.uname = ""
                        member.gname = ""
                        member.pax_headers = {}
                        if content is None:
                            output.addfile(member)
                        else:
                            from io import BytesIO

                            output.addfile(member, BytesIO(content))
        os.replace(temporary, source)
    finally:
        if temporary.exists():
            temporary.unlink()
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sdist", type=Path)
    parser.add_argument(
        "--epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", "0")),
    )
    args = parser.parse_args()
    print(normalize_sdist(args.sdist, args.epoch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
