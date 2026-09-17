# Evidência Sprint 0

- Pacote: 14/14 itens com SHA-256 correspondente ao manifesto.
- Baseline antes da transição: `59 passed, 42 subtests passed`.
- Gate default após transição: `51 passed, 42 subtests passed`.
- `t doctor`: não sondou/importou PyTorch.
- `t benchmark ...` sem opt-in: bloqueado antes de executar workload.
- CI/release: extras `science` removidos; experimentos SIMD/Borboleta removidos.
- Evidência histórica: preservada nos caminhos originais.

Resultado: `SPRINT_0_PASS`, aceitação P0 `PASS` dentro do escopo auditado.
