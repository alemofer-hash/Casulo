"""Casulo: Otimização conservativa do tráfego de informação."""

from .casulo import Casulo, evoluir
from .marca import ASSINATURA_DO_INVENTO, INVENTOR, MARCA
from .modelos import Borboleta, Crisalida, FaseEvolucao, Larva, Metamorfose, Ovo

__all__ = [
    "ASSINATURA_DO_INVENTO",
    "Borboleta",
    "Casulo",
    "Crisalida",
    "FaseEvolucao",
    "INVENTOR",
    "Larva",
    "MARCA",
    "Metamorfose",
    "Ovo",
    "evoluir",
]

__version__ = "0.1.0"

