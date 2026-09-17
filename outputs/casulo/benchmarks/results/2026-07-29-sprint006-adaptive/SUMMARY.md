# Sprint 006 — matriz adaptativa

## Protocolo

- artefato: `sha256:8ab8635722c96aaa4f17fa158199ad9b6b8bbe755fa1e53cb7fc79c2c9fd0ee2`;
- Casulo Borboleta: `casulo-borboleta/0.2`;
- modelo: `casulo-cost-model/0.1`;
- 2.000 registros por lote;
- 9 amostras × 5 iterações;
- 2 aquecimentos;
- 2.000 reamostragens bootstrap;
- semente: `6006`;
- ambiente: Intel Core i5-1235U, 16 GB RAM, Windows 11, Python 3.13.2.

O fator é `tempo_escalar / tempo_adaptativo`. Acima de 1 favorece o Casulo.
Perfil, decisão e execução estão todos dentro do tempo adaptativo.

## Resultados

| Repetição | Estimada | Decisão | Dedup forçado | Veredito forçado | Adaptativo | IC95% adaptativo | Veredito adaptativo |
|---:|---:|---|---:|---|---:|---:|---|
| 0% | 0,00% | `RECALCULATE` | 0,550× | regressão | 1,091× | 0,901–1,278 | inconclusivo |
| 25% | 20,85% | `RECALCULATE` | 0,553× | regressão | 0,941× | 0,864–1,040 | inconclusivo |
| 50% | 51,30% | `RECALCULATE` | 0,731× | regressão | 1,077× | 0,986–1,119 | inconclusivo |
| 75% | 70,90% | `RECALCULATE` | 0,826× | regressão | 1,014× | 0,866–1,160 | inconclusivo |
| 90% | 91,25% | `RECALCULATE` | 1,049× | inconclusivo | 1,084× | 1,031–1,176 | melhoria |
| 95% | 95,20% | `DEDUPLICATE_BATCH` | 1,020× | inconclusivo | 0,927× | 0,886–1,076 | inconclusivo |
| 99% | 99,00% | `DEDUPLICATE_BATCH` | 1,197× | inconclusivo | 1,106× | 1,023–1,242 | melhoria |

## Conclusão limitada

O seletor evitou a deduplicação nos quatro regimes em que ela apresentou
regressão conclusiva. Nenhum ponto apresentou regressão adaptativa conclusiva.
Em 99%, o caminho adaptativo apresentou melhoria ponta a ponta conclusiva de
1,106× na mediana.

Os resultados não demonstram equivalência com centenas de processadores, não
medem joules e não generalizam para outros kernels ou máquinas sem replicação.
Eles demonstram uma propriedade menor e necessária: a linguagem e o runtime
podem escolher uma otimização de tráfego com custo limitado e conservar a
semântica da carga medida.
