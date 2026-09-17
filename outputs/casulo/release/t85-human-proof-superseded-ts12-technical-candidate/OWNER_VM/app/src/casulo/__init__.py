"""Casulo: Otimização conservativa do tráfego de informação."""

from .casulo import Casulo, evoluir
from .marca import ASSINATURA_DO_INVENTO, AUTORIA_PUBLICA, MARCA
from .modelos import Borboleta, Crisalida, FaseEvolucao, Larva, Metamorfose, Egg

__all__ = [
    "ASSINATURA_DO_INVENTO",
    "AUTORIA_PUBLICA",
    "Borboleta",
    "Casulo",
    "Crisalida",
    "FaseEvolucao",
    "Larva",
    "MARCA",
    "Metamorfose",
    "Egg",
    "evoluir",
]

__version__ = "0.23.0a1"
