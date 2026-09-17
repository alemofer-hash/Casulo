# TS5 — autoridades críticas do owner

## Resultado

As quatro decisões críticas foram deslocadas para módulos T/2.0 compilados e
executados pelo runtime Rust produtivo:

| Superfície | Módulo T | Resultado autorizador |
| --- | --- | --- |
| material intent | `owner.critical.intent` | `MATERIAL` |
| capabilities/effects | `owner.critical.capabilities` | `AUTHORIZED` |
| HARD fulfillment | `owner.critical.fulfillment` | `FULFILLED` |
| publish/commit | `owner.critical.publish` | `COMMIT` |

O modelo apenas propõe. Confirmação, consentimento, grants e evidências entram
como fatos externos com proveniência; o runtime T decide se eles são suficientes.
Python valida o envelope causal e transporta a decisão. A primitive estrangeira
de materialização só é chamada depois do receipt `COMMIT` e não possui fallback
afirmativo.

## Fronteira honesta

Este gate não afirma que todo o owner já é soberano em T. Ele eleva somente as
quatro superfícies críticas a `d=1`. Planejamento de evidências, verificadores,
memória, roteamento, diálogo, jobs e lifecycle continuam com grau zero até os
sprints correspondentes. O probe é um gate contratual, não a prova humana.

## Provas

- sources T reais, sem `emit_literal` ou receipt posterior;
- AST, typed IR e TCAP v2 content-addressed;
- quatro receipts causais emitidos por `t-runtime/rust-2.0`;
- resultado `COMMIT` consumido antes da única chamada à primitive;
- `UNKNOWN`, grant ausente, confirmação ausente e publish não aprovado bloqueiam;
- mutação do source T muda a decisão;
- remoção do runtime falha fechado;
- artefato limpo contém runtime, TCAP e transportes exatos.

O score intermediário esperado é `29/65 = 0,446153846...`, com
`C_critical=1`. O target global de `0,85` continua pendente.
