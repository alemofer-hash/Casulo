# Casulo

Casulo é um invento original de **Guimo** para **Otimização de Tráfego de
Informação**.

Ele recebe uma fonte integral, reconhece sua estrutura, mede o atrito da
travessia, escolhe um tratamento, reorganiza o conteúdo sem descarte silencioso
e libera uma **Borboleta**: a informação completa, mais navegável, enriquecida
e acompanhada por prova de conservação.

## A evolução

```text
Ovo
  → Larva
    → Crisálida
      → Metamorfose
        → Borboleta
```

- **Ovo**: fonte original, imutável e identificada por hash.
- **Larva**: conteúdo ingerido, inventariado e perfilado.
- **Crisálida**: decisão e plano de tratamento.
- **Metamorfose**: reorganização conservativa e enriquecimentos.
- **Borboleta**: pacote integral otimizado e verificável.

O **Casulo** é o orquestrador de todas as fases.

## Lei do invento

Todo conteúdo recebido precisa aparecer:

1. no conteúdo integral reorganizado; ou
2. na quarentena, com motivo explícito.

O contador `descartes_silenciosos` precisa ser sempre zero.

## Uso Python

```python
from casulo import Casulo

borboleta = Casulo().evoluir(
    "entrada.csv",
    destino="saida-casulo",
)

print(borboleta.prova_conservacao)
```

## Linha de comando

```powershell
python -m casulo entrada.csv --destino saida-casulo
```

Um perfil opcional em JSON pode definir campos esperados, aliases, campo
temporal e volume de referência:

```json
{
  "nome": "operacao",
  "campos_esperados": ["timestamp", "origem", "valor"],
  "aliases": {
    "data_hora": "timestamp"
  },
  "campo_temporal": "timestamp",
  "volume_referencia_bytes": 100000
}
```

```powershell
python -m casulo entrada.csv --destino saida --perfil perfil.json
```

## Pacote liberado

```text
saida/
├─ 00_ovo/
│  └─ fonte_original.*
├─ 01_larva/
│  └─ inventario.json
├─ 02_crisalida/
│  └─ plano_de_evolucao.json
├─ 03_metamorfose/
│  ├─ conteudo_integral.jsonl
│  ├─ quarentena.jsonl
│  └─ enriquecimentos.json
├─ 04_borboleta/
│  ├─ indice.json
│  └─ prova_de_conservacao.json
├─ MARCA_E_AUTORIA.txt
└─ manifesto.json
```

## Formatos iniciais

- CSV/TSV e outros delimitadores comuns;
- JSON;
- texto linha a linha;
- XLSX quando `openpyxl` estiver instalado.

Formatos não compreendidos continuam fisicamente preservados no Ovo e são
liberados na quarentena, nunca descartados.

## Validação

```powershell
python -m unittest discover -s tests -v
```

## Autoria

Veja [NOTICE.md](NOTICE.md). O crédito `Guimo` é provisório até o inventor
definir seu nome público formal.

