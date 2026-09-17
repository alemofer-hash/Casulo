# Sprint 023 — estabilidade em P-cores

## Integridade

- pré-registro commitado antes da execução;
- afinidade efetiva: `[0, 1, 2, 3]`;
- duração-alvo: 250 ms;
- lote compartilhado calibrado: 512 invocações;
- todos os backends alcançaram o alvo;
- cadeia verificada;
- energia elétrica não medida: `null`.

## Resultado metrológico

| backend | CV | limite | estado |
|---|---:|---:|---|
| Casulo/T | 13,65% | 15% | passou |
| PyTorch eager | 30,35% | 15% | falhou |
| PyTorch Inductor | 44,61% | 15% | falhou |

Classificação: `INCONCLUSIVE`.

As medianas de velocidade estão no relatório para auditabilidade, mas o Juiz
bloqueou qualquer interpretação ou claim. O próximo ataque aumenta a janela de
medição e compara topologias fixadas por estabilidade, não por velocidade.
