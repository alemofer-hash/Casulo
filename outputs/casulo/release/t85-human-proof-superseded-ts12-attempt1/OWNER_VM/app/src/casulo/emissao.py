from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .marca import texto_de_atribuicao
from .modelos import Borboleta, tornar_jsonavel


def emitir_borboleta(borboleta: Borboleta, destino: str | Path) -> Borboleta:
    raiz = Path(destino).expanduser().resolve()
    egg_dir = raiz / "00_egg"
    larva_dir = raiz / "01_larva"
    crisalida_dir = raiz / "02_crisalida"
    metamorfose_dir = raiz / "03_metamorfose"
    borboleta_dir = raiz / "04_borboleta"
    for pasta in (egg_dir, larva_dir, crisalida_dir, metamorfose_dir, borboleta_dir):
        pasta.mkdir(parents=True, exist_ok=True)

    egg = borboleta.metamorfose.crisalida.larva.egg
    copia_fonte = egg_dir / f"fonte_original{egg.extensao or '.bin'}"
    copia_fonte.write_bytes(egg.conteudo)
    if hashlib.sha256(copia_fonte.read_bytes()).hexdigest() != egg.sha256:
        raise RuntimeError("falha_ao_preservar_egg")

    _escrever_json(
        larva_dir / "inventario.json",
        borboleta.metamorfose.crisalida.larva.resumo(),
    )
    _escrever_json(
        crisalida_dir / "plano_de_evolucao.json",
        borboleta.metamorfose.crisalida.resumo(),
    )
    _escrever_jsonl(
        metamorfose_dir / "conteudo_integral.jsonl",
        borboleta.metamorfose.conteudo_integral,
    )
    _escrever_jsonl(
        metamorfose_dir / "quarentena.jsonl",
        borboleta.metamorfose.quarentena,
    )
    _escrever_json(
        metamorfose_dir / "enriquecimentos.json",
        borboleta.metamorfose.enriquecimentos,
    )
    _escrever_json(borboleta_dir / "indice.json", borboleta.indice)
    _escrever_json(
        borboleta_dir / "prova_de_conservacao.json",
        borboleta.prova_conservacao,
    )
    (raiz / "MARCA_E_AUTORIA.txt").write_text(
        texto_de_atribuicao(),
        encoding="utf-8",
    )

    manifesto = dict(borboleta.manifesto)
    manifesto["arquivos"] = _manifestar_arquivos(raiz)
    _escrever_json(raiz / "manifesto.json", manifesto)
    return Borboleta(
        metamorfose=borboleta.metamorfose,
        prova_conservacao=borboleta.prova_conservacao,
        indice=borboleta.indice,
        manifesto=manifesto,
        destino=raiz,
    )


def _escrever_json(caminho: Path, carga: Any) -> None:
    caminho.write_text(
        json.dumps(
            tornar_jsonavel(carga),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _escrever_jsonl(caminho: Path, itens: Iterable[Mapping[str, Any]]) -> None:
    linhas = [
        json.dumps(
            tornar_jsonavel(item),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        for item in itens
    ]
    caminho.write_text(("\n".join(linhas) + "\n") if linhas else "", encoding="utf-8")


def _manifestar_arquivos(raiz: Path) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    for caminho in sorted(item for item in raiz.rglob("*") if item.is_file()):
        if caminho.name == "manifesto.json":
            continue
        conteudo = caminho.read_bytes()
        saida.append(
            {
                "caminho": caminho.relative_to(raiz).as_posix(),
                "quantidade_bytes": len(conteudo),
                "sha256": hashlib.sha256(conteudo).hexdigest(),
            }
        )
    return saida
