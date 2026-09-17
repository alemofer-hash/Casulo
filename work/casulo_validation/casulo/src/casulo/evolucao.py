from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .marca import ASSINATURA_DO_INVENTO, INVENTOR, MARCA
from .modelos import Borboleta, Crisalida, Larva, Metamorfose, Ovo, tornar_jsonavel


SINAIS_DE_ATRITO = (
    "variacao_cabecalho",
    "proporcao_nulos",
    "delta_volume",
    "taxa_desvio_temporal",
    "delta_colunas",
    "delta_conteineres",
    "divergencia_semantica",
    "lacuna_cobertura",
)

PESOS_POLINOMIAIS = (0.35, 0.30, 0.22, 0.13)


def receber_ovo(fonte: str | Path) -> Ovo:
    caminho = Path(fonte).expanduser().resolve()
    if not caminho.is_file():
        raise FileNotFoundError(f"Fonte não encontrada: {caminho}")
    conteudo = caminho.read_bytes()
    return Ovo(
        caminho=caminho,
        nome=caminho.name,
        extensao=caminho.suffix.lower(),
        sha256=hashlib.sha256(conteudo).hexdigest(),
        quantidade_bytes=len(conteudo),
        conteudo=conteudo,
    )


def alimentar_larva(
    ovo: Ovo,
    perfil: Mapping[str, Any] | None = None,
) -> Larva:
    perfil_ativo = dict(perfil or {})
    extensao = ovo.extensao
    avisos: list[str] = []

    if extensao in {".csv", ".tsv", ".txt", ".log"}:
        texto, codificacao = _decodificar(ovo.conteudo)
        if extensao in {".txt", ".log"} and not _parece_tabela(texto):
            registros = tuple(
                {"conteudo": linha, "_linha_origem": indice}
                for indice, linha in enumerate(texto.splitlines(), start=1)
            )
            campos = ("conteudo", "_linha_origem")
            formato = "texto"
            separador = None
        else:
            registros, campos, separador = _ler_delimitado(texto, extensao)
            formato = "delimitado"
        conteineres = (ovo.nome,)
    elif extensao == ".json":
        texto, codificacao = _decodificar(ovo.conteudo)
        registros, campos = _ler_json(texto)
        formato = "json"
        separador = None
        conteineres = (ovo.nome,)
    elif extensao in {".xlsx", ".xlsm"}:
        registros, campos, conteineres, avisos_xlsx = _ler_xlsx(ovo.caminho)
        avisos.extend(avisos_xlsx)
        formato = "xlsx"
        codificacao = None
        separador = None
    else:
        registros = ()
        campos = ()
        conteineres = (ovo.nome,)
        formato = "binario_nao_interpretado"
        codificacao = None
        separador = None
        avisos.append("formato_sem_adaptador_semantico; fonte_preservada_na_quarentena")

    sinais = _medir_atrito(
        ovo=ovo,
        registros=registros,
        campos=campos,
        conteineres=conteineres,
        perfil=perfil_ativo,
    )
    inventario = _inventariar(
        ovo=ovo,
        formato=formato,
        registros=registros,
        campos=campos,
        conteineres=conteineres,
        perfil=perfil_ativo,
    )
    return Larva(
        ovo=ovo,
        formato=formato,
        codificacao=codificacao,
        separador=separador,
        conteineres=tuple(conteineres),
        campos=tuple(campos),
        registros=tuple(registros),
        sinais_de_atrito=sinais,
        inventario=inventario,
        avisos=tuple(avisos),
    )


def formar_crisalida(larva: Larva) -> Crisalida:
    sinais = [float(larva.sinais_de_atrito.get(nome, 0.0)) for nome in SINAIS_DE_ATRITO]
    intensidade = _limitar(sum(sinais) / max(len(sinais), 1))
    maior_sinal = max(sinais, default=0.0)
    risco = _limitar(max(intensidade, maior_sinal * 0.80))
    custo = _custo_polinomial(intensidade)
    volume = _volume_exato(intensidade)
    fase_matematica = math.atan2(volume, max(custo, 1e-12))

    if larva.formato == "binario_nao_interpretado":
        decisao, severidade = "QUARENTENA", "CRITICA"
    elif risco >= 0.82:
        decisao, severidade = "QUARENTENA", "CRITICA"
    elif risco >= 0.62:
        decisao, severidade = "REESTRUTURAR", "ALTA"
    elif risco >= 0.38:
        decisao, severidade = "REVISAR", "MODERADA"
    else:
        decisao, severidade = "PROSSEGUIR", "BAIXA"

    razoes = tuple(
        f"{nome}={valor:.4f}"
        for nome, valor in larva.sinais_de_atrito.items()
        if float(valor) >= 0.38
    ) or ("atrito_abaixo_do_limiar_de_revisao",)
    operacoes = (
        "preservar_fonte_original",
        "atribuir_identidade_aos_registros",
        "preservar_campos_originais",
        "criar_indice_de_navegacao",
        "calcular_estatisticas_de_campos",
        "verificar_conservacao",
    )
    if decisao == "REESTRUTURAR":
        operacoes += ("criar_mapa_de_campos_normalizados",)
    if decisao == "QUARENTENA":
        operacoes += ("isolar_sem_descartar",)

    return Crisalida(
        larva=larva,
        intensidade_de_atrito=intensidade,
        custo_de_evolucao=custo,
        volume_de_transformacao=volume,
        fase_matematica=fase_matematica,
        decisao=decisao,
        severidade=severidade,
        razoes=razoes,
        operacoes=operacoes,
        pesos=PESOS_POLINOMIAIS,
    )


def realizar_metamorfose(crisalida: Crisalida) -> Metamorfose:
    registros_entrada = [dict(registro) for registro in crisalida.larva.registros]
    hash_entrada = _hash_semantico(registros_entrada)
    conteudo_integral: list[dict[str, Any]] = []
    quarentena: list[dict[str, Any]] = []

    if crisalida.decisao == "QUARENTENA":
        if registros_entrada:
            for indice, original in enumerate(registros_entrada, start=1):
                quarentena.append(
                    {
                        "_casulo": {
                            "registro_id": _registro_id(crisalida.larva.ovo.sha256, indice),
                            "ordem_origem": indice,
                            "motivo": "crisalida_determinou_quarentena",
                        },
                        "original": original,
                    }
                )
        else:
            quarentena.append(
                {
                    "_casulo": {
                        "registro_id": _registro_id(crisalida.larva.ovo.sha256, 0),
                        "ordem_origem": 0,
                        "motivo": "conteudo_preservado_apenas_como_ovo",
                    },
                    "original": {
                        "nome": crisalida.larva.ovo.nome,
                        "sha256": crisalida.larva.ovo.sha256,
                        "quantidade_bytes": crisalida.larva.ovo.quantidade_bytes,
                    },
                }
            )
    else:
        for indice, original in enumerate(registros_entrada, start=1):
            conteudo_integral.append(
                {
                    "_casulo": {
                        "registro_id": _registro_id(crisalida.larva.ovo.sha256, indice),
                        "ordem_origem": indice,
                        "campos_normalizados": {
                            _normalizar_nome(campo): campo for campo in original.keys()
                        },
                    },
                    "original": original,
                }
            )

    registros_saida = [
        dict(item["original"])
        for item in (*conteudo_integral, *quarentena)
        if isinstance(item.get("original"), Mapping)
        and not (
            item["_casulo"]["ordem_origem"] == 0
            and crisalida.larva.formato == "binario_nao_interpretado"
        )
    ]
    hash_saida = _hash_semantico(registros_saida)
    enriquecimentos = {
        "marca": MARCA,
        "inventor": INVENTOR,
        "assinatura": ASSINATURA_DO_INVENTO,
        "estatisticas_de_campos": _estatisticas_de_campos(registros_entrada),
        "mapa_de_navegacao": {
            _normalizar_nome(campo): campo for campo in crisalida.larva.campos
        },
    }
    transformacoes = tuple(
        {
            "ordem": indice,
            "operacao": operacao,
            "preserva_original": True,
        }
        for indice, operacao in enumerate(crisalida.operacoes, start=1)
    )
    return Metamorfose(
        crisalida=crisalida,
        conteudo_integral=tuple(conteudo_integral),
        quarentena=tuple(quarentena),
        enriquecimentos=enriquecimentos,
        transformacoes=transformacoes,
        hash_semantico_entrada=hash_entrada,
        hash_semantico_saida=hash_saida,
    )


def libertar_borboleta(metamorfose: Metamorfose) -> Borboleta:
    larva = metamorfose.crisalida.larva
    registros_entrada = len(larva.registros)
    registros_contabilizados = len(metamorfose.conteudo_integral)
    if larva.formato != "binario_nao_interpretado":
        registros_contabilizados += len(metamorfose.quarentena)
    valores_entrada = sum(len(registro) for registro in larva.registros)
    valores_contabilizados = sum(
        len(item["original"])
        for item in (*metamorfose.conteudo_integral, *metamorfose.quarentena)
        if isinstance(item.get("original"), Mapping)
        and item["_casulo"]["ordem_origem"] > 0
    )
    fonte_binaria_preservada = bool(larva.ovo.conteudo) or larva.ovo.quantidade_bytes == 0
    hashes_semanticos_iguais = (
        metamorfose.hash_semantico_entrada == metamorfose.hash_semantico_saida
    )
    descartes = max(0, registros_entrada - registros_contabilizados)
    prova = {
        "registros_entrada": registros_entrada,
        "registros_contabilizados": registros_contabilizados,
        "valores_entrada": valores_entrada,
        "valores_contabilizados": valores_contabilizados,
        "campos_entrada": len(larva.campos),
        "campos_contabilizados": len(larva.campos),
        "conteudo_quarentena": len(metamorfose.quarentena),
        "descartes_silenciosos": descartes,
        "hash_semantico_entrada": metamorfose.hash_semantico_entrada,
        "hash_semantico_saida": metamorfose.hash_semantico_saida,
        "hashes_semanticos_iguais": hashes_semanticos_iguais,
        "fonte_fisica_preservada": fonte_binaria_preservada,
        "cobertura": 1.0 if descartes == 0 else registros_contabilizados / max(registros_entrada, 1),
        "aprovada": (
            descartes == 0
            and valores_entrada == valores_contabilizados
            and hashes_semanticos_iguais
            and fonte_binaria_preservada
        ),
    }
    if larva.formato == "binario_nao_interpretado":
        prova["aprovada"] = (
            descartes == 0
            and fonte_binaria_preservada
            and len(metamorfose.quarentena) == 1
        )
        prova["hashes_semanticos_iguais"] = True

    indice = {
        "campos": list(larva.campos),
        "conteineres": list(larva.conteineres),
        "quantidade_registros": registros_entrada,
        "formato": larva.formato,
        "decisao_da_crisalida": metamorfose.crisalida.decisao,
        "sinais_de_atrito": dict(larva.sinais_de_atrito),
    }
    manifesto = {
        "marca": MARCA,
        "inventor": INVENTOR,
        "assinatura_do_invento": ASSINATURA_DO_INVENTO,
        "fonte": larva.ovo.resumo(),
        "fases": ["OVO", "LARVA", "CRISALIDA", "METAMORFOSE", "BORBOLETA"],
        "prova_aprovada": bool(prova["aprovada"]),
    }
    return Borboleta(
        metamorfose=metamorfose,
        prova_conservacao=prova,
        indice=indice,
        manifesto=manifesto,
    )


def _decodificar(conteudo: bytes) -> tuple[str, str]:
    for codificacao in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return conteudo.decode(codificacao), codificacao
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace"), "utf-8-replacement"


def _parece_tabela(texto: str) -> bool:
    primeira = next((linha for linha in texto.splitlines() if linha.strip()), "")
    return any(separador in primeira for separador in (";", ",", "\t", "|"))


def _ler_delimitado(
    texto: str,
    extensao: str,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], str]:
    amostra = texto[:8192]
    padrao = "\t" if extensao == ".tsv" else ","
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t|")
        separador = dialeto.delimiter
    except csv.Error:
        separador = padrao
    leitor = csv.reader(io.StringIO(texto), delimiter=separador)
    linhas = list(leitor)
    if not linhas:
        return (), (), separador
    cabecalho = _cabecalho_unico(linhas[0])
    todos_campos = list(cabecalho)
    registros: list[dict[str, Any]] = []
    for numero_linha, valores in enumerate(linhas[1:], start=2):
        largura = max(len(cabecalho), len(valores))
        campos = list(cabecalho)
        while len(campos) < largura:
            campos.append(f"_campo_extra_{len(campos) + 1}")
        todos_campos.extend(campos)
        preenchidos = list(valores) + [None] * (largura - len(valores))
        registro = {campos[indice]: preenchidos[indice] for indice in range(largura)}
        registro["_linha_origem"] = numero_linha
        registros.append(registro)
    campos_finais = tuple(dict.fromkeys((*todos_campos, "_linha_origem")))
    return tuple(registros), campos_finais, separador


def _cabecalho_unico(valores: Iterable[Any]) -> list[str]:
    usados: dict[str, int] = {}
    saida: list[str] = []
    for indice, valor in enumerate(valores, start=1):
        base = str(valor).strip() or f"_campo_sem_nome_{indice}"
        usados[base] = usados.get(base, 0) + 1
        nome = base if usados[base] == 1 else f"{base}__{usados[base]}"
        saida.append(nome)
    return saida


def _ler_json(texto: str) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    carga = json.loads(texto)
    itens = carga if isinstance(carga, list) else [carga]
    registros: list[dict[str, Any]] = []
    campos: list[str] = []
    for indice, item in enumerate(itens, start=1):
        registro = dict(item) if isinstance(item, Mapping) else {"valor": item}
        registro["_ordem_origem"] = indice
        registros.append(registro)
        campos.extend(str(campo) for campo in registro.keys())
    return tuple(registros), tuple(dict.fromkeys(campos))


def _ler_xlsx(
    caminho: Path,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], tuple[str, ...], list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return (), (), (caminho.name,), [
            "openpyxl_ausente; fonte_preservada_na_quarentena"
        ]
    workbook = load_workbook(caminho, read_only=True, data_only=False)
    registros: list[dict[str, Any]] = []
    campos_globais: list[str] = []
    try:
        for planilha in workbook.worksheets:
            linhas = planilha.iter_rows(values_only=True)
            primeira = next(linhas, None)
            if primeira is None:
                continue
            cabecalho = _cabecalho_unico(primeira)
            campos_globais.extend(cabecalho)
            for numero_linha, valores in enumerate(linhas, start=2):
                registro = {
                    cabecalho[indice]: valores[indice] if indice < len(valores) else None
                    for indice in range(len(cabecalho))
                }
                registro["_planilha_origem"] = planilha.title
                registro["_linha_origem"] = numero_linha
                registros.append(registro)
        campos_globais.extend(("_planilha_origem", "_linha_origem"))
        return (
            tuple(registros),
            tuple(dict.fromkeys(campos_globais)),
            tuple(workbook.sheetnames),
            [],
        )
    finally:
        workbook.close()


def _medir_atrito(
    *,
    ovo: Ovo,
    registros: tuple[Mapping[str, Any], ...],
    campos: tuple[str, ...],
    conteineres: tuple[str, ...],
    perfil: Mapping[str, Any],
) -> dict[str, float]:
    esperados = tuple(str(item) for item in perfil.get("campos_esperados", ()))
    aliases = {
        _normalizar_nome(str(origem)): _normalizar_nome(str(destino))
        for origem, destino in dict(perfil.get("aliases", {})).items()
    }
    normalizados = {_normalizar_nome(campo) for campo in campos}
    normalizados_com_alias = {aliases.get(campo, campo) for campo in normalizados}
    esperados_norm = {_normalizar_nome(campo) for campo in esperados}
    faltantes = esperados_norm - normalizados_com_alias
    valores = [valor for registro in registros for valor in registro.values()]
    nulos = sum(valor is None or (isinstance(valor, str) and not valor.strip()) for valor in valores)
    proporcao_nulos = nulos / max(len(valores), 1)

    volume_ref = int(perfil.get("volume_referencia_bytes", 0) or 0)
    delta_volume = (
        _limitar(abs(ovo.quantidade_bytes - volume_ref) / max(volume_ref, 1))
        if volume_ref
        else 0.0
    )
    delta_colunas = (
        _limitar(abs(len(campos) - len(esperados)) / max(len(esperados), 1))
        if esperados
        else 0.0
    )
    conteineres_ref = int(perfil.get("quantidade_conteineres_esperada", 0) or 0)
    delta_conteineres = (
        _limitar(abs(len(conteineres) - conteineres_ref) / max(conteineres_ref, 1))
        if conteineres_ref
        else 0.0
    )
    campo_temporal = _normalizar_nome(str(perfil.get("campo_temporal", "") or ""))
    taxa_desvio_temporal = 0.0
    lacuna_cobertura = 0.0
    if campo_temporal:
        campo_real = next(
            (campo for campo in campos if _normalizar_nome(campo) == campo_temporal),
            None,
        )
        if campo_real is None:
            taxa_desvio_temporal = 1.0
            lacuna_cobertura = 1.0
        else:
            temporais = [registro.get(campo_real) for registro in registros]
            invalidos = sum(not _e_temporal(valor) for valor in temporais)
            taxa_desvio_temporal = invalidos / max(len(temporais), 1)
            lacuna_cobertura = 1.0 if not temporais else 0.0

    variacao_cabecalho = _limitar(len(faltantes) / max(len(esperados_norm), 1)) if esperados else 0.0
    divergencia_semantica = variacao_cabecalho
    return {
        "variacao_cabecalho": variacao_cabecalho,
        "proporcao_nulos": _limitar(proporcao_nulos),
        "delta_volume": delta_volume,
        "taxa_desvio_temporal": _limitar(taxa_desvio_temporal),
        "delta_colunas": delta_colunas,
        "delta_conteineres": delta_conteineres,
        "divergencia_semantica": divergencia_semantica,
        "lacuna_cobertura": lacuna_cobertura,
    }


def _inventariar(
    *,
    ovo: Ovo,
    formato: str,
    registros: tuple[Mapping[str, Any], ...],
    campos: tuple[str, ...],
    conteineres: tuple[str, ...],
    perfil: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "marca": MARCA,
        "inventor": INVENTOR,
        "formato": formato,
        "quantidade_bytes": ovo.quantidade_bytes,
        "quantidade_registros": len(registros),
        "quantidade_campos": len(campos),
        "quantidade_conteineres": len(conteineres),
        "campos": list(campos),
        "conteineres": list(conteineres),
        "perfil": tornar_jsonavel(perfil),
    }


def _estatisticas_de_campos(
    registros: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    campos = list(dict.fromkeys(campo for registro in registros for campo in registro.keys()))
    estatisticas: dict[str, dict[str, Any]] = {}
    for campo in campos:
        valores = [registro.get(campo) for registro in registros]
        nulos = sum(valor is None or (isinstance(valor, str) and not valor.strip()) for valor in valores)
        estatisticas[campo] = {
            "quantidade": len(valores),
            "nulos": nulos,
            "preenchidos": len(valores) - nulos,
            "tipos_observados": sorted({type(valor).__name__ for valor in valores}),
        }
    return estatisticas


def _hash_semantico(registros: list[dict[str, Any]]) -> str:
    codificado = json.dumps(
        tornar_jsonavel(registros),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(codificado).hexdigest()


def _registro_id(sha256_fonte: str, ordem: int) -> str:
    return hashlib.sha256(f"{sha256_fonte}:{ordem}".encode("utf-8")).hexdigest()[:24]


def _normalizar_nome(valor: str) -> str:
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", valor.strip().lower()).strip("_")
    return texto or "campo"


def _e_temporal(valor: Any) -> bool:
    if valor is None or str(valor).strip() == "":
        return False
    if hasattr(valor, "isoformat"):
        return True
    texto = str(valor).strip()
    try:
        datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    for formato in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            datetime.strptime(texto, formato)
            return True
        except ValueError:
            continue
    return False


def _custo_polinomial(intensidade: float) -> float:
    return sum(
        peso * intensidade**grau
        for grau, peso in enumerate(PESOS_POLINOMIAIS, start=1)
    )


def _volume_exato(intensidade: float) -> float:
    pesos = (0.0, *PESOS_POLINOMIAIS)
    total = 0.0
    for i in range(1, 5):
        for j in range(1, 5):
            total += pesos[i] * pesos[j] * intensidade ** (i + j + 1) / (i + j + 1)
    return total


def _limitar(valor: float) -> float:
    if not math.isfinite(float(valor)):
        return 0.0
    return max(0.0, min(1.0, float(valor)))
