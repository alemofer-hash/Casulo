# Sprint 023 — incidente metrológico preservado

Classificação independente: `INCONCLUSIVE`.

As opções de afinidade, cooldown e máximo de iterações não foram ligadas ao
comando do laboratório. O pré-registro selou os padrões reais e o relatório os
respeitou. Além disso, a primeira invocação continuou depois do timeout do
invólucro e se sobrepôs à tentativa seguinte.

Consequências:

- nenhum número de speedup desta rodada será usado;
- o relatório e o veredito permanecem imutáveis;
- a correção exige novo commit e novo pré-registro;
- a instabilidade observada reforça a necessidade do Sprint 023.
