from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo import AUTORIA_PUBLICA, Casulo, MARCA


class CasuloTests(unittest.TestCase):
    def test_csv_evolui_sem_descartar_conteudo(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            fonte = raiz / "entrada.csv"
            fonte.write_text(
                "timestamp;origem;valor;observacao\n"
                "2026-01-01T00:00:00;A;10;primeiro\n"
                "2026-01-01T01:00:00;B;;segundo\n",
                encoding="utf-8",
            )
            destino = raiz / "saida"
            borboleta = Casulo().evoluir(
                fonte,
                destino=destino,
                perfil={
                    "campos_esperados": ["timestamp", "origem", "valor", "observacao"],
                    "campo_temporal": "timestamp",
                },
            )

            self.assertTrue(borboleta.prova_conservacao["aprovada"])
            self.assertEqual(borboleta.prova_conservacao["descartes_silenciosos"], 0)
            self.assertEqual(len(borboleta.conteudo_integral), 2)
            self.assertEqual(
                borboleta.conteudo_integral[1]["original"]["observacao"],
                "segundo",
            )
            self.assertEqual(
                borboleta.conteudo_integral[1]["original"]["valor"],
                "",
            )
            copia = destino / "00_ovo" / "fonte_original.csv"
            self.assertEqual(
                hashlib.sha256(copia.read_bytes()).hexdigest(),
                hashlib.sha256(fonte.read_bytes()).hexdigest(),
            )

    def test_json_preserva_objetos_integrais(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            fonte = raiz / "entrada.json"
            carga = [
                {"id": 1, "dados": {"a": 10, "b": [1, 2]}},
                {"id": 2, "dados": None},
            ]
            fonte.write_text(json.dumps(carga), encoding="utf-8")
            borboleta = Casulo().evoluir(fonte)

            self.assertTrue(borboleta.prova_conservacao["aprovada"])
            self.assertEqual(
                borboleta.conteudo_integral[0]["original"]["dados"]["b"],
                [1, 2],
            )

    def test_formato_desconhecido_e_preservado_em_quarentena(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            fonte = raiz / "entrada.bin"
            fonte.write_bytes(b"\x00\x01\x02casulo")
            destino = raiz / "saida"
            borboleta = Casulo().evoluir(fonte, destino=destino)

            self.assertTrue(borboleta.prova_conservacao["aprovada"])
            self.assertEqual(len(borboleta.quarentena), 1)
            self.assertEqual(borboleta.metamorfose.crisalida.decisao, "QUARENTENA")
            self.assertEqual(
                (destino / "00_ovo" / "fonte_original.bin").read_bytes(),
                fonte.read_bytes(),
            )

    def test_marca_e_autoria_acompanham_a_borboleta(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            fonte = raiz / "entrada.txt"
            fonte.write_text("uma linha\nduas linhas\n", encoding="utf-8")
            destino = raiz / "saida"
            borboleta = Casulo().evoluir(fonte, destino=destino)

            self.assertEqual(borboleta.manifesto["marca"], MARCA)
            self.assertEqual(
                borboleta.manifesto["autoria_publica"],
                AUTORIA_PUBLICA,
            )
            atribuicao = (destino / "MARCA_E_AUTORIA.txt").read_text(encoding="utf-8")
            self.assertIn(MARCA, atribuicao)
            self.assertIn(AUTORIA_PUBLICA, atribuicao)

    def test_xlsx_preserva_planilhas_e_formulas_quando_adapter_disponivel(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl não instalado")

        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            fonte = raiz / "entrada.xlsx"
            workbook = Workbook()
            primeira = workbook.active
            primeira.title = "Dados"
            primeira.append(["id", "valor", "dobro"])
            primeira.append([1, 10, "=B2*2"])
            segunda = workbook.create_sheet("Notas")
            segunda.append(["texto"])
            segunda.append(["preservar tudo"])
            workbook.save(fonte)
            workbook.close()

            borboleta = Casulo().evoluir(fonte)
            self.assertTrue(borboleta.prova_conservacao["aprovada"])
            self.assertEqual(len(borboleta.conteudo_integral), 2)
            self.assertEqual(
                borboleta.conteudo_integral[0]["original"]["dobro"],
                "=B2*2",
            )
            self.assertEqual(
                set(borboleta.metamorfose.crisalida.larva.conteineres),
                {"Dados", "Notas"},
            )

    def test_atrito_alto_forma_crisalida_de_quarentena(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            fonte = raiz / "entrada.csv"
            fonte.write_text("x;y\n;\n", encoding="utf-8")
            borboleta = Casulo().evoluir(
                fonte,
                perfil={
                    "campos_esperados": ["timestamp", "origem", "valor"],
                    "campo_temporal": "timestamp",
                    "quantidade_conteineres_esperada": 5,
                    "volume_referencia_bytes": 1000000,
                },
            )
            self.assertIn(
                borboleta.metamorfose.crisalida.decisao,
                {"REESTRUTURAR", "QUARENTENA"},
            )
            self.assertTrue(borboleta.prova_conservacao["aprovada"])


if __name__ == "__main__":
    unittest.main()
