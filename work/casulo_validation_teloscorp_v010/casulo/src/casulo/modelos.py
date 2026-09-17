from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class FaseEvolucao(str, Enum):
    OVO = "OVO"
    LARVA = "LARVA"
    CRISALIDA = "CRISALIDA"
    METAMORFOSE = "METAMORFOSE"
    BORBOLETA = "BORBOLETA"


@dataclass(frozen=True)
class Ovo:
    """A fonte original antes de qualquer interpretação."""

    caminho: Path
    nome: str
    extensao: str
    sha256: str
    quantidade_bytes: int
    conteudo: bytes = field(repr=False)
    fase: FaseEvolucao = FaseEvolucao.OVO

    def resumo(self) -> dict[str, Any]:
        return {
            "fase": self.fase.value,
            "arquivo_de_origem": self.nome,
            "nome": self.nome,
            "extensao": self.extensao,
            "sha256": self.sha256,
            "quantidade_bytes": self.quantidade_bytes,
        }


@dataclass(frozen=True)
class Larva:
    """A fonte ingerida, inventariada e pronta para crescer."""

    ovo: Ovo
    formato: str
    codificacao: str | None
    separador: str | None
    conteineres: tuple[str, ...]
    campos: tuple[str, ...]
    registros: tuple[Mapping[str, Any], ...]
    sinais_de_atrito: Mapping[str, float]
    inventario: Mapping[str, Any]
    avisos: tuple[str, ...] = ()
    fase: FaseEvolucao = FaseEvolucao.LARVA

    def resumo(self) -> dict[str, Any]:
        return {
            "fase": self.fase.value,
            "formato": self.formato,
            "codificacao": self.codificacao,
            "separador": self.separador,
            "conteineres": list(self.conteineres),
            "campos": list(self.campos),
            "quantidade_registros": len(self.registros),
            "sinais_de_atrito": dict(self.sinais_de_atrito),
            "inventario": dict(self.inventario),
            "avisos": list(self.avisos),
            "ovo": self.ovo.resumo(),
        }


@dataclass(frozen=True)
class Crisalida:
    """A decisão que encerra a ingestão e define a evolução segura."""

    larva: Larva
    intensidade_de_atrito: float
    custo_de_evolucao: float
    volume_de_transformacao: float
    fase_matematica: float
    decisao: str
    severidade: str
    razoes: tuple[str, ...]
    operacoes: tuple[str, ...]
    pesos: tuple[float, ...]
    fase: FaseEvolucao = FaseEvolucao.CRISALIDA

    def resumo(self) -> dict[str, Any]:
        return {
            "fase": self.fase.value,
            "intensidade_de_atrito": self.intensidade_de_atrito,
            "custo_de_evolucao": self.custo_de_evolucao,
            "volume_de_transformacao": self.volume_de_transformacao,
            "fase_matematica": self.fase_matematica,
            "decisao": self.decisao,
            "severidade": self.severidade,
            "razoes": list(self.razoes),
            "operacoes": list(self.operacoes),
            "pesos": list(self.pesos),
        }


@dataclass(frozen=True)
class Metamorfose:
    """A transformação conservativa em andamento e seu rastro."""

    crisalida: Crisalida
    conteudo_integral: tuple[Mapping[str, Any], ...]
    quarentena: tuple[Mapping[str, Any], ...]
    enriquecimentos: Mapping[str, Any]
    transformacoes: tuple[Mapping[str, Any], ...]
    hash_semantico_entrada: str
    hash_semantico_saida: str
    fase: FaseEvolucao = FaseEvolucao.METAMORFOSE

    def resumo(self) -> dict[str, Any]:
        return {
            "fase": self.fase.value,
            "quantidade_conteudo_integral": len(self.conteudo_integral),
            "quantidade_quarentena": len(self.quarentena),
            "enriquecimentos": dict(self.enriquecimentos),
            "transformacoes": [dict(item) for item in self.transformacoes],
            "hash_semantico_entrada": self.hash_semantico_entrada,
            "hash_semantico_saida": self.hash_semantico_saida,
        }


@dataclass(frozen=True)
class Borboleta:
    """A informação integral liberada em forma otimizada."""

    metamorfose: Metamorfose
    prova_conservacao: Mapping[str, Any]
    indice: Mapping[str, Any]
    manifesto: Mapping[str, Any]
    destino: Path | None = None
    fase: FaseEvolucao = FaseEvolucao.BORBOLETA

    @property
    def conteudo_integral(self) -> tuple[Mapping[str, Any], ...]:
        return self.metamorfose.conteudo_integral

    @property
    def quarentena(self) -> tuple[Mapping[str, Any], ...]:
        return self.metamorfose.quarentena

    def resumo(self) -> dict[str, Any]:
        return {
            "fase": self.fase.value,
            "destino": str(self.destino) if self.destino else None,
            "prova_conservacao": dict(self.prova_conservacao),
            "indice": dict(self.indice),
            "manifesto": dict(self.manifesto),
            "metamorfose": self.metamorfose.resumo(),
        }


def tornar_jsonavel(valor: Any) -> Any:
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, Path):
        return str(valor)
    if hasattr(valor, "resumo") and callable(valor.resumo):
        return tornar_jsonavel(valor.resumo())
    if isinstance(valor, Mapping):
        return {str(chave): tornar_jsonavel(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [tornar_jsonavel(item) for item in valor]
    if hasattr(valor, "isoformat") and callable(valor.isoformat):
        return valor.isoformat()
    return valor
