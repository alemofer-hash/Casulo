# Sprint 010 — AOT, arena e Marco 3

## Corpus

- protocolo: `casulo-native-benchmark/0.2`;
- artefato:
  `sha256:323fe3e5b15f968314bf85146849a60387681f1885b973ca0d51baaad9719a70`;
- dataset:
  `9dd1386e92761aa022ea1362ad8d0aa5bb9f17e41362295ec4c6676d7505eddf`;
- 2.000 registros;
- 2.000 registros únicos;
- duplicação: 0%;
- operação: `WaterBalance`;
- amostras: 21 × cinco iterações.

## Resultado

| Caminho | ns/registro mediano |
|---|---:|
| Python escalar completo | 11.899,13 |
| C99 completo | 2.029,06 |
| marshal | 652,92 |
| kernel C99 | 4,0409 |
| manifestação | 1.336,92 |

- razão das medianas: `5,864×`;
- mediana pareada: `5,966×`;
- IC95% pareado: `5,866×–6,169×`;
- CPU: `3,500×`;
- equivalência: `true`;
- `marco_3_exit_reached`: `true`.

O kernel puro representa aproximadamente `0,20%` da soma independente dos
estágios. A manifestação continua sendo o maior custo de fronteira.

Arquivos:

- [relatório completo](native-benchmark-unique.json);
- [dataset integral](dataset.json);
- [manifesto do dataset](dataset-manifest.json).

O arquivo JSON contém todas as amostras, ambiente, compilador, SHA-256 do
binário, decomposição e parâmetros do bootstrap.

Validação da entrega:

- Python 3.13: 87 testes e 42 subtestes;
- Python 3.11/3.12: 86 testes, um skip esperado e 42 subtestes;
- cobertura: 86%;
- wheel e sdist reproduzíveis e aprovados pelo `twine check`;
- instalação limpa e execução nativa obrigatória aprovadas.
