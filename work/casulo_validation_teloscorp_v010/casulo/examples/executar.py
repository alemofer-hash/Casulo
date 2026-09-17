from pathlib import Path
import sys

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from casulo import Casulo

borboleta = Casulo().evoluir(
    Path(__file__).with_name("entrada_exemplo.csv"),
    destino=Path(__file__).with_name("saida_exemplo"),
    perfil={
        "nome": "trafego-de-informacao",
        "campos_esperados": [
            "timestamp",
            "origem",
            "destino",
            "mensagem",
            "prioridade",
        ],
        "campo_temporal": "timestamp",
    },
)

print(borboleta.prova_conservacao)

