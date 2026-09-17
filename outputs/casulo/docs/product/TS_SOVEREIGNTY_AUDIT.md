# TS1 — baseline honesto de soberania

Gate: `TS1_HONEST_SOVEREIGNTY_BASELINE_PASS`  
Matriz: 13 superfícies, peso total 65, congelada no TS0.

## Resultado anterior à migração

```text
S_authority = 0.00
S_execution = 0.00
C_critical  = 0.00
P_authority = 1.00
```

O valor zero é intencional e honesto. Os nove contratos RC4 executam T em um
audit delimitado, mas não são a fonte autoritativa das decisões no launcher
owner empacotado. O comportamento generativo baseado em `emit_literal`, TCAP
com `RET`, wrappers Python e decisões recompostas pelo broker/materializer não
recebem crédito T85.

## Instrumentação

`src/casulo/t/authority.py` introduz:

- a matriz tipada por superfície;
- `DecisionTrace` com causalidade observável;
- `TDecisionReceipt` canônico e hash-chained, que exige identidade
  `t-runtime/*`;
- cálculo de `S_authority`, `S_execution`, `C_critical` e `P_authority`;
- proibição operacional de promover shadow, resultado ignorado ou recomputação.

Os mutation/bypass probes demonstram que uma superfície não chega a grau 1 se
alterar T não alterar a decisão ou se retirar T não falhar fechado. Programa
trivial recebe zero em execução.

O arquivo canônico do baseline é
`product-demos/t85-sovereign-engine/ts01-honest-baseline-attempt1/authority-baseline.json`.
Ele atribui a fonte atual de cada decisão a arquivos Python reais e não oculta
as superfícies críticas em zero.

## Limite

Esta instrumentação é o medidor, não a migração. Receipts reais futuros devem
nascer no runtime que executa o programa T e ser consumidos pelo caminho owner
limpo. Um wrapper que apenas instancia a dataclass não ganha autoridade.

