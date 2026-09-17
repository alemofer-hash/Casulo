# Sprint 023 — pré-registro corrigido e verificado

Rodada exploratória, inelegível para claim, criada após a correção
`0.24.0a2`.

Antes do commit e antes da execução, um verificador leu o JSON e confirmou:

- afinidade `[0, 1, 2, 3]`;
- cooldown de 50 ms;
- duração-alvo de 250 ms;
- máximo de 4096 invocações;
- CV máximo de 15%.

O grafo já foi observado no Sprint 022 e não é um holdout. Um diretório de
pré-registro anterior ficou indisponível por bloqueio de I/O antes de ser
commitado e nunca será executado.

## Resultado

O laboratório aplicou a afinidade correta, calibrou 512 invocações por lote e
alcançou o alvo em todos os backends. O Juiz classificou `INCONCLUSIVE`:

- Casulo/T: CV `13,65%`;
- PyTorch eager: CV `30,35%`;
- PyTorch Inductor: CV `44,61%`;
- claim: `null`.

A estabilidade do candidato passou, mas a dos dois baselines não. As medianas
de velocidade não constituem evidência utilizável nesta rodada.
