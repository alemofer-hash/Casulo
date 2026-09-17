# Sprint 007 — matriz da chave estrutural

## Protocolo

- artefato: `sha256:24b27cebe7831ebfdc1838ce7ec6b8299e1721ba2334012dbb6b4981edee50dc`;
- chave: `casulo-structural-key/0.1`;
- modelo: `casulo-cost-model/0.2`;
- Borboleta: `casulo-borboleta/0.3`;
- 2.000 registros por lote;
- semente: `7020`;
- ensaios gerais: 9 amostras × 5 iterações, 2 aquecimentos;
- fronteira de 40%: 21 amostras × 10 iterações, 3 aquecimentos;
- bootstrap: 2.000; fronteira: 5.000;
- ambiente: Intel Core i5-1235U, 16 GB RAM, Windows 11, Python 3.13.2.

O fator é `tempo_escalar / tempo_casulo`. Perfil, decisão e execução estão
incluídos no fator adaptativo.

| Repetição | Estimada | Decisão | Kernel | IC95% | Adaptativo | IC95% | Veredito |
|---:|---:|---|---:|---:|---:|---:|---|
| 0% | 0,00% | `RECALCULATE` | 0,839× | 0,756–0,969 | 1,004× | 0,956–1,014 | inconclusivo |
| 25% | 19,75% | `RECALCULATE` | 0,914× | 0,856–0,993 | 0,949× | 0,841–1,008 | inconclusivo |
| 40% | 32,95% | `DEDUPLICATE_BATCH` | 1,111× | 1,095–1,202 | 1,079× | 1,039–1,176 | melhoria |
| 50% | 66,30% | `DEDUPLICATE_BATCH` | 1,096× | 0,988–1,328 | 1,169× | 0,966–1,256 | inconclusivo |
| 75% | 66,30% | `DEDUPLICATE_BATCH` | 1,434× | 1,382–1,593 | 1,402× | 1,256–1,697 | melhoria |
| 90% | 88,05% | `DEDUPLICATE_BATCH` | 1,842× | 1,489–1,880 | 1,668× | 1,320–1,754 | melhoria |
| 99% | 99,10% | `DEDUPLICATE_BATCH` | 2,015× | 1,933–2,203 | 2,031× | 1,869–2,263 | melhoria |

## Conclusão limitada

O break-even demonstrado desceu de aproximadamente 95% para 40% de repetição.
O seletor evitou a deduplicação nos regimes baixos e não apresentou regressão
adaptativa conclusiva. A evidência não mede energia elétrica nem autoriza
extrapolação para outros kernels ou máquinas sem replicação.
