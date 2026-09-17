# ADR-0001 — Produto acima de benchmark

- Status: ACCEPTED
- Data: 2026-08-11
- Decisor: Guilherme Moura Fernandes

## Contexto

O Casulo chegou a este checkpoint como Research Preview, com ferramentas de
equivalência, tempo, energia, temperatura e comparação com PyTorch. O objetivo
ativo mudou para um produto voice-first, local-first, com memória, intenção
incremental, simulação e materialização.

## Decisão

1. O GOAL científico está `SUPERSEDED_BY_PRODUCT_GOAL_2026_08_11`.
2. Benchmarks, RAPL, HWiNFO, ablações, IC95% e paper gates não participam do
   build, teste, release ou definição de pronto padrão.
3. A evidência histórica permanece intacta nos caminhos originais; não será
   apagada, reinterpretada ou apresentada como claim do produto.
4. Comandos históricos longos no CLI T exigem
   `CASULO_ENABLE_LEGACY_RESEARCH=1`.
5. Permanecem testes curtos de correção, segurança, compatibilidade e budgets
   de UX. Proteção térmica continua sendo segurança, não critério de feature.

## Registro histórico imutável

```text
historical_speedup_median = 8.957846
historical_ci95 = [8.075179, 9.872416]
historical_pairs = 21
t_median_ms = 35.3111
eager_median_ms = 337.0635
electrical_energy_measured = false
joules = null
```

## Consequências

O produto avança sem depender de wattímetro, refrigeração ou PyTorch. Uma
campanha científica futura exigirá autorização separada e não alterará
retroativamente esta decisão.
