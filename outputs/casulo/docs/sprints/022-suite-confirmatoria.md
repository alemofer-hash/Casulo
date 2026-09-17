# Sprint 022 — Suíte confirmatória multi-caso

**Versão:** `0.23.0a1`  
**Estado final:** suíte concluída; veredito agregado `NEGATIVE`

## Pergunta

O sinal observado no MLP médio sobrevive quando shapes e profundidade mudam,
quando cada repetição nasce em um processo novo e quando nenhum caso pode ser
descartado depois do resultado?

## Casos reservados

| caso | arquitetura | shapes principais |
|---|---|---|
| `tall-batch` | MLP de duas camadas | `384×48 → 96 → 12` |
| `wide-input` | MLP de duas camadas | `96×192 → 64 → 24` |
| `deep-bottleneck` | MLP de três camadas | `160×72 → 144 → 48 → 16` |

Os arquivos são definidos em `examples/tensor-suite/cases.json`. Planejar e
validar os grafos não observa desempenho; a primeira medição só pode ocorrer
depois que o pré-registro for commitado.

## Desenho

- 3 casos;
- 3 reinícios por caso;
- 9 processos Python independentes;
- 9 amostras pareadas por processo;
- 2 warmups;
- 25 invocações internas por amostra;
- orçamento de 4 workers;
- OpenBLAS com 1 thread interna;
- PyTorch eager e Inductor obrigatórios;
- agenda latina: cada caso ocupa cada posição uma vez por ciclo.

Cada processo executa o laboratório tensorial completo:

1. recompila o backend num cache isolado;
2. prepara eager e Inductor;
3. prova paridade contra NumPy;
4. mede nas seis ordens balanceadas;
5. produz relatório e veredito filhos.

## Regra de decisão

Os casos filhos nunca podem liberar claim. O Juiz da suíte classifica:

- `POSITIVE`: todos os nove vereditos são positivos contra os dois baselines;
- `NEGATIVE`: ao menos um veredito é negativo;
- `NULL`: nenhum é negativo, mas existe resultado nulo;
- `INCONCLUSIVE`: execução obrigatória ausente;
- `INVALID`: integridade, agenda ou cadeia filha violada.

Não existe média capaz de esconder um caso ruim. Ganhar muito em dois casos
não compensa perder no terceiro.

## Limites que permanecem

- uma única máquina;
- apenas CPU e float32;
- topologias MLP;
- energia elétrica ainda não instrumentada;
- processo novo não equivale a reinício do sistema operacional;
- caches do sistema operacional e estado térmico físico continuam possíveis.

Uma conclusão positiva será forte dentro desse escopo, mas não universal.

## Resultado

Os nove processos terminaram e todas as cadeias passaram:

- Casulo/T versus eager: `9 POSITIVE`;
- Casulo/T versus Inductor: `2 POSITIVE`, `6 NULL`, `1 NEGATIVE`;
- integridade: zero falhas;
- execuções ausentes: zero;
- classificação agregada: `NEGATIVE`;
- claim: bloqueado.

O caso que refutou a hipótese foi `tall-batch`, reinício 2, contra Inductor:
mediana `0,728×`, IC95% `[0,652×, 0,840×]`.

O resultado é simultaneamente promissor e restritivo. A vantagem sobre eager
generalizou nos três workloads. A vantagem sobre Inductor não foi estável o
suficiente para sustentar a tese forte.
