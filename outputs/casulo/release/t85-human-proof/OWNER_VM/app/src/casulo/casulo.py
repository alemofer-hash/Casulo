from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .emissao import emitir_borboleta
from .evolucao import (
    alimentar_larva,
    formar_crisalida,
    libertar_borboleta,
    realizar_metamorfose,
    receber_egg,
)
from .modelos import Borboleta


class Casulo:
    """Orquestra a evolução integral da informação."""

    def evoluir(
        self,
        fonte: str | Path,
        *,
        destino: str | Path | None = None,
        perfil: Mapping[str, Any] | str | Path | None = None,
    ) -> Borboleta:
        perfil_ativo = _carregar_perfil(perfil)
        egg = receber_egg(fonte)
        larva = alimentar_larva(egg, perfil_ativo)
        crisalida = formar_crisalida(larva)
        metamorfose = realizar_metamorfose(crisalida)
        borboleta = libertar_borboleta(metamorfose)
        if not bool(borboleta.prova_conservacao["aprovada"]):
            raise RuntimeError("metamorfose_reprovada_por_perda_de_informacao")
        if destino is not None:
            borboleta = emitir_borboleta(borboleta, destino)
        return borboleta


def evoluir(
    fonte: str | Path,
    *,
    destino: str | Path | None = None,
    perfil: Mapping[str, Any] | str | Path | None = None,
) -> Borboleta:
    return Casulo().evoluir(fonte, destino=destino, perfil=perfil)


def _carregar_perfil(
    perfil: Mapping[str, Any] | str | Path | None,
) -> dict[str, Any]:
    if perfil is None:
        return {}
    if isinstance(perfil, Mapping):
        return dict(perfil)
    caminho = Path(perfil).expanduser().resolve()
    carga = json.loads(caminho.read_text(encoding="utf-8-sig"))
    if not isinstance(carga, dict):
        raise ValueError("perfil_precisa_ser_objeto_json")
    return carga

