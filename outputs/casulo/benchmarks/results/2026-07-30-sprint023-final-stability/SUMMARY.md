# Sprint 023 — gate final de estabilidade

| backend | CV | limite | estado |
|---|---:|---:|---|
| Casulo/T | 5,51% | 15% | passou |
| PyTorch eager | 13,97% | 15% | passou |
| PyTorch Inductor | 16,08% | 15% | falhou |

Classificação: `INCONCLUSIVE`.

O laboratório aplicou afinidade `[0, 1, 2, 3]`, confirmou alimentação externa,
calibrou 2048 invocações compartilhadas e verificou toda a cadeia. O limite não
foi alterado após o resultado. Speedups observados permanecem sem força de
claim porque estabilidade precede velocidade.
