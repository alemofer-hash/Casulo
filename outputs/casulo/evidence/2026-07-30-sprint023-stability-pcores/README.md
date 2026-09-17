# Sprint 023 — rodada exploratória em P-cores

Esta evidência mede a estabilidade do laboratório corrigido. Ela não é elegível
para claim porque o grafo `heldout-tall` já foi observado no Sprint 022.

## Incidente de execução preservado

Este diretório inicialmente descrevia o desenho pretendido na linha de comando.
Depois do pré-registro, a inspeção do JSON revelou um erro de ligação no CLI:
as opções metrológicas foram aceitas pelo parser, mas não chegaram à função do
laboratório. O pré-registro imutável é a autoridade e selou:

- 7 amostras e 2 warmups;
- calibração causal até 250 ms por backend;
- máximo de 1.000.000 de invocações;
- cooldown de 0 ms;
- 4 workers e GEMM com 1 thread;
- OpenBLAS auditado;
- nenhuma afinidade de CPU;
- CV máximo de 15%;
- PyTorch eager e Inductor obrigatórios;
- claim sempre bloqueado.

O relatório foi preservado e julgado, sem correção posterior:

- Casulo/T: CV `8,04%`;
- PyTorch eager: CV `26,33%`;
- PyTorch Inductor: CV `64,73%`;
- classificação: `INCONCLUSIVE`;
- claim: `null`.

O processo curto lançado primeiro foi interrompido pelo invólucro do terminal,
mas concluiu e materializou o relatório. A repetição concorrente encontrou o
artefato imutável e foi bloqueada. Por cautela, a rodada inteira permanece
incidente metrológico e não será usada para inferir desempenho.

O erro do CLI exige nova versão de implementação e novo pré-registro. Nenhum
arquivo desta cadeia será substituído.
