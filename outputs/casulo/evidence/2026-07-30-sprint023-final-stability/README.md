# Sprint 023 — gate final de estabilidade

O perfil `p2-smt` foi selecionado exclusivamente porque apresentou o menor CV
agregado na matriz pré-registrada. Speedup não participou da escolha.

Desenho:

- 7 amostras;
- lote de no mínimo 2 segundos por backend;
- cooldown de 500 ms;
- afinidade `[0, 1, 2, 3]`;
- 4 workers, OpenBLAS com uma thread;
- CV máximo de 15%;
- eager e Inductor obrigatórios;
- claim bloqueado.

O mesmo grafo e o perfil de topologia já foram observados. O pré-registro marca
explicitamente a repetição e a janela de 2 segundos como mudança metrológica.

## Resultado

- Casulo/T: CV `5,51%`;
- PyTorch eager: CV `13,97%`;
- PyTorch Inductor: CV `16,08%`;
- limite: `15%`;
- classificação: `INCONCLUSIVE`;
- claim: `null`.

O Inductor excedeu o gate por 1,08 ponto percentual. O limite não foi relaxado
depois do resultado.
