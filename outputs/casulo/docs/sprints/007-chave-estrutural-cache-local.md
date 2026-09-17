# Sprint 007 — chave estrutural e cache local

## Problema

O backend anterior serializava cada entrada em JSON canônico e calculava
SHA-256 antes de deduplicar. No kernel barato `WaterBalance`, esse custo exigia
aproximadamente 95% de repetição para produzir ganho.

## Entrega

- `casulo-structural-key/0.1`;
- identidade sensível a tipos e independente da ordem de objetos;
- especialização AOT para esquemas numéricos;
- fingerprint curto somente para telemetria;
- resolução de colisões por igualdade estrutural completa;
- cache de lote restrito a uma chamada;
- clonador especializado para valores JSON;
- perfil por pares coincidentes;
- `RECALCULATE` ligado ao caminho escalar;
- artefato 0.4, backend 0.3.1 e Borboleta 0.3.

## Gates

1. conservar integralmente a projeção semântica;
2. distinguir inteiro, float, booleano e sinal de zero;
3. não depender da ordem dos campos de objetos;
4. sobreviver a colisão de fingerprint sem falso hit;
5. descartar o cache ao final do lote;
6. demonstrar break-even abaixo de 50%;
7. não apresentar regressão adaptativa conclusiva em 0% ou 25%.

## Resultado

O ensaio de fronteira em 40%, com 21 amostras de dez iterações, apresentou:

- kernel deduplicado: `1,111×`, IC95% `1,095–1,202`;
- adaptativo ponta a ponta: `1,079×`, IC95% `1,039–1,176`;
- previsão: correta;
- equivalência semântica: preservada.

Em 99%, o adaptativo atingiu `2,031×`, com IC95% `1,869–2,263`.

Os manifestos, amostras e relatórios HTML/JSON estão indexados no
[resumo da matriz experimental](../../benchmarks/results/2026-07-29-sprint007-structural/SUMMARY.md).

Os resultados pertencem ao kernel, dataset e computador declarados. Não
equivalem a multiplicação universal de núcleos nem medem joules.
