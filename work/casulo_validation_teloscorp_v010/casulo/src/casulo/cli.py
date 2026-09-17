from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .casulo import Casulo
from .marca import ASSINATURA_DO_INVENTO
from .modelos import tornar_jsonavel


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casulo",
        description=ASSINATURA_DO_INVENTO,
    )
    parser.add_argument("fonte", help="Arquivo integral a ser evoluído.")
    parser.add_argument(
        "--destino",
        required=True,
        help="Pasta em que a Borboleta será liberada.",
    )
    parser.add_argument(
        "--perfil",
        help="Perfil JSON opcional para medir atrito e orientar a Crisálida.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    borboleta = Casulo().evoluir(
        Path(args.fonte),
        destino=Path(args.destino),
        perfil=Path(args.perfil) if args.perfil else None,
    )
    print(ASSINATURA_DO_INVENTO)
    print(
        json.dumps(
            tornar_jsonavel(borboleta.resumo()),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

