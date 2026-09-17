# Sprint 023 — Estabilidade metrológica

**Versão:** `0.24.0a2`
**Estado:** implementação concluída; gate final `INCONCLUSIVE`

## Problema observado

A suíte do Sprint 022 executou lotes de apenas 25 invocações. Em vários casos,
o lote completo durou poucos milissegundos. No Windows e num processador
híbrido, essa fronteira era pequena diante de escalonamento, frequência,
interrupções e migração entre P-cores e E-cores. O coeficiente de variação entre
processos chegou a aproximadamente 40–51% para o candidato.

Esse diagnóstico não apaga o resultado negativo. Ele explica por que o próximo
experimento precisa de uma fronteira metrológica mais forte.

## Contrato implementado

O pré-registro agora sela:

- duração mínima do lote por backend;
- mínimo e máximo de invocações internas;
- algoritmo de calibração;
- afinidade lógica de CPU;
- cooldown entre amostras;
- coeficiente de variação máximo;
- política de telemetria.

A calibração ocorre depois dos warmups e antes das amostras. Cada backend dobra
seu lote até alcançar a duração-alvo. O maior número requerido vira um único
lote compartilhado por todos. A calibração não calcula speedup, não escolhe
vencedor e não remove observações.

## Máquina híbrida

No Windows, `GetLogicalProcessorInformationEx` registra:

- classe de eficiência de cada núcleo;
- CPUs lógicas pertencentes ao núcleo;
- presença de SMT.

A afinidade solicitada é aplicada ao processo inteiro e restaurada ao final.
Uma CPU fora do conjunto permitido interrompe a execução em vez de produzir
um relatório parcialmente aderente.

## Juiz

O Juiz recalcula o coeficiente de variação das amostras brutas. A ordem de
decisão é:

1. violação de integridade ou qualidade: `INVALID`;
2. baseline ausente ou instabilidade acima do limite: `INCONCLUSIVE`;
3. IC95% inteiramente abaixo de 1: `NEGATIVE`;
4. todos os IC95% inteiramente acima de 1: `POSITIVE`;
5. caso restante: `NULL`.

Assim, uma máquina instável não pode produzir claim, mesmo que a mediana pareça
favorável.

## Execução exploratória recomendada

```console
t tensor-lab-preregister examples/tensor-suite/heldout-tall.tensor.json \
  --output evidence/2026-07-30-sprint023/preregistration.json \
  --wrt weight1 weight2 \
  --samples 7 \
  --warmups 2 \
  --inner-iterations 16 \
  --target-sample-ms 250 \
  --maximum-inner-iterations 4096 \
  --cooldown-ms 50 \
  --workers 4 \
  --gemm-workers 1 \
  --provider openblas \
  --cpu-affinity 0 1 2 3 \
  --max-cv 0.15 \
  --claim-ineligible \
  --prior-exploratory-disclosure "Grafo observado no Sprint 022; desenho metrológico novo."
```

Essa rodada é desenvolvimento. Os grafos do Sprint 022 deixaram de ser holdout
e não podem sustentar uma nova alegação confirmatória.

## Fechamento

Uma matriz pré-registrada comparou P-cores com e sem SMT, E-cores e topologia
mista usando lotes de 1 segundo. `p2-smt` foi selecionado somente por menor CV.
O gate final dobrou a janela para 2 segundos e obteve:

- Casulo/T: `5,51%`;
- eager: `13,97%`;
- Inductor: `16,08%`.

Como o limite selado era 15%, o Juiz retornou `INCONCLUSIVE`. A infraestrutura
metrológica está operacional; o ambiente não cumpriu estabilidade universal
para o Inductor. Nenhuma mediana dessa rodada pode sustentar claim.
