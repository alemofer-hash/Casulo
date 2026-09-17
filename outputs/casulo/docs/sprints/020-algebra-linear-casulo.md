# Sprint 020 — Álgebra Linear Casulo/T

## Estado

Implementação funcional; exploração de desenvolvimento concluída; rodada
oficial ainda não pré-registrada.

## Entregas

- contrato `EggGemmContract`;
- diagnóstico `LarvaTrafficProfile`;
- plano `CrisalidaGemmPlan`;
- auditor `BorboletaAlgebraAudit`;
- identidade SHA-256 de cada decisão;
- seleção de ordem de laços por strides;
- transpostas do backward zero-copy;
- reduções de identidade zero-copy;
- redução contígua sem cálculo genérico de offset;
- paralelismo evitado em regiões pequenas;
- modo de auditoria separado da fronteira medida;
- FMA declarada sem habilitar `fast-math`;
- testes determinísticos, de recusa e de paridade.

## Resultado exploratório

Todos os números abaixo são diagnósticos de desenvolvimento. Eles não passaram
por pré-registro congelado e não autorizam claim.

| Variante | Casulo | Eager | Inductor | Paridade |
|---|---:|---:|---:|---|
| Sprint 019 oficial, backend anterior | 4,270 ms | 1,055 ms | 0,472 ms | PASS |
| ordem por trânsito + sondas separadas | 2,276 ms | 1,404 ms | 0,947 ms | PASS |
| aliases + reduções especializadas | 1,458 ms | 0,777 ms | 0,332 ms | PASS |
| FMA declarada | 1,427 ms | 0,900 ms | 0,343 ms | PASS |
| bloqueio de linhas experimental | 1,435 ms | 0,846 ms | 0,390 ms | PASS |

Os baselines oscilaram entre processos; por isso os tempos de linhas diferentes
não devem ser transformados em uma comparação pareada. Dentro da última rodada
ativa antes do bloqueio rejeitado, o speedup baseline/Casulo foi:

- eager: `0,631×`;
- Inductor: `0,241×`.

O Torch continua vencedor. A Álgebra Casulo reduziu seu próprio tempo em cerca
de `3×` em relação ao resultado congelado, mas isso também permanece
exploratório até uma nova rodada oficial.

## Hipótese rejeitada

O bloqueio manual das linhas de `Xᵀ @ dY` não trouxe ganho verificável no shape
ensaiado. A rota não foi mantida no núcleo ativo.

## Próxima fronteira

1. ABI de provedores GEMM com proveniência obrigatória;
2. packing persistente e cache por shape/stride/dtype;
3. autotuning isolado do conjunto de avaliação;
4. fusão de epílogos e backward;
5. novo pré-registro, commit e experimento oficial;
6. energia somente quando houver contador físico cumulativo disponível.
