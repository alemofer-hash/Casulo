# Sprint 023 — matriz fixa de estabilidade

Quatro perfis foram selados juntos antes de qualquer execução. O objetivo é
reduzir variabilidade, não encontrar o maior speedup.

| perfil | CPUs lógicas | workers | interpretação |
|---|---|---:|---|
| `p2-no-smt` | `0, 2` | 2 | um thread por P-core |
| `p2-smt` | `0, 1, 2, 3` | 4 | dois threads por P-core |
| `e4` | `4, 5, 6, 7` | 4 | quatro E-cores físicos |
| `p2-e2` | `0, 2, 4, 5` | 4 | dois P-cores e dois E-cores |

Contrato comum:

- 7 amostras;
- duração-alvo de 1 segundo por backend;
- cooldown de 250 ms;
- limite de 8192 invocações;
- CV máximo de 15%;
- OpenBLAS com uma thread;
- eager e Inductor obrigatórios;
- claim bloqueado.

Todos os perfis serão executados uma vez e todos os resultados serão
preservados. A escolha de configuração só pode considerar CV e aderência
metrológica. Velocidade não participa dessa decisão.

## Resultado

| perfil | CV Casulo | CV eager | CV Inductor | Juiz |
|---|---:|---:|---:|---|
| `p2-no-smt` | 34,04% | 31,16% | 47,10% | `INCONCLUSIVE` |
| `p2-smt` | 5,88% | 19,16% | 16,74% | `INCONCLUSIVE` |
| `e4` | 25,28% | 51,03% | 44,58% | `INCONCLUSIVE` |
| `p2-e2` | 12,54% | 22,38% | 23,32% | `INCONCLUSIVE` |

`p2-smt` foi o perfil mais estável pela regra pré-declarada, mas os dois
baselines ainda ultrapassaram 15%. Nenhuma mediana de velocidade foi liberada
como evidência.
