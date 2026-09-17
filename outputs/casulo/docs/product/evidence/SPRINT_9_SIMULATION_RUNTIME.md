# Evidência — Sprint 9 Simulation Runtime

Data: 2026-08-11

Estado: `SPRINT_9_SIMULATION_RUNTIME_PASS`

## Invariantes executáveis

- somente `SimulationCapabilityDouble` first-party é aceito;
- o double possui respostas estáticas e nenhum callback capaz de fazer I/O;
- toda capability precisa estar declarada na criação;
- preflight valida todos os passos antes da primeira tentativa;
- payload máximo: 64 KiB; plano máximo: 128 passos;
- ciclos, dependências ausentes e providers reais falham fechados;
- eventos formam cadeia SHA-256;
- uma falha interrompe dependentes e retorna `correction_paths`;
- correção nunca é aplicada automaticamente;
- receipts declaram `real_effects_executed=false`.

## Demonstração

Uma tentativa virtual de `network.connect` retornou `timeout virtual`, apontou
`behavior.tone`, e não executou rede. Após a fala confirmada
`defina behavior.tone como resiliente`, o Forge recompilou `behavior` e
`interface`, reutilizou `identity` com o mesmo hash e a segunda simulação passou
com resposta estática `{status: 202, virtual: true}`.

```powershell
python -m pytest tests/product/test_simulation.py -q
python -m casulo.product.simulation_demo
```

Gate focal: `6 passed`. Gate integral: `243 passed, 42 subtests passed`.
Auditoria public: `12` arquivos, zero achado privado. Nenhum benchmark
científico novo foi iniciado.
