# Biblioteca padrão soberana T/2.0

Status: TS4 PASS. Escopo: biblioteca e vertical slice simulada; integração no
owner começa em TS5.

## Módulos

`t.core.result`, `t.core.collections`, `t.core.canonical`, `t.casulo.intent`,
`t.casulo.requirements`, `t.casulo.capabilities`, `t.casulo.memory_policy`,
`t.casulo.jobs`, `t.casulo.universes`, `t.casulo.simulation`,
`t.casulo.materialization`, `t.casulo.dialogue` e `t.casulo.receipts`.

Cada módulo possui contrato tipado, budgets e função executável. A vertical
slice transporta a saída T anterior como precondição do próximo módulo. O host
Python escreve input canônico, chama a VM Rust e valida o receipt; ele não
recalcula a decisão.

```text
PASS -> ALL_PASS -> CANONICAL -> MATERIAL -> VERIFIED -> AUTHORIZED
     -> MEMORY_SELECTED -> JOBS_READY -> ROUTED -> SIMULATED -> PUBLISHED
     -> ANNOUNCE -> SEALED
```

## Fail-closed exercitado

- `UNKNOWN` em requisito HARD bloqueia antes de capability/publicação;
- projeto divergente é `project_bleed_denied`;
- remoção de `t.casulo.intent` quebra a precondição seguinte;
- mutação da saída MATERIAL muda a decisão e bloqueia downstream;
- effect é apenas solicitado quando existe grant correspondente;
- os receipts formam cadeia, e nenhum receipt é sintetizado pelo runner.

## Fronteiras

`TS_FOREIGN_BOUNDARIES.json` manifesta runtime, filesystem e primitives owner.
Na demonstração TS4, `simulation` e `manifest` são effects simulados: foram
registrados, mas nenhum simulador ou packager real foi acionado.

## Limites

Esta biblioteca ainda não substitui as decisões Python do owner RC13. Ela não
conta para `S_authority` até o caminho owner consumir os resultados, mutation e
bypass passarem, e o artefato limpo carregar os TCAPs e runtime corretos.
