# Evidência — Sprint 10 Materializer e API local

Data: 2026-08-11

Estado: `SPRINT_10_MATERIALIZER_PASS`

## Entrega

O Materializer só aceita criação em `AGREEMENT`, simulação correspondente em
`PASS` e `real_effects_executed=false`. A exportação é feita em staging
confinado, sem overwrite, e publicada somente depois de todos os hashes.

Pacote de demonstração:

`product-demos/materialized-sprint10/creation-8e8797df3721cf50-v1.casulo.zip`

SHA-256:

`4c996a2af141b0b9ff7f8543b2bfc2fb6acb524c2f70a81c419c1e2eb226e4c3`

Conteúdo: `creation.json`, `forge-receipt.json`, `simulation-receipt.json`,
`api.py`, `MANIFEST.json`, `SBOM.spdx.json` e `SHA256SUMS`.

O ZIP é determinístico. A API liga somente em `127.0.0.1`, limita body e expõe
apenas estado/simulação selados; não executa effects reais. Secret keys/PEM são
recusados antes de qualquer exportação. O manifest declara
`engine-agnostic-no-owner-components`.

```powershell
python -m pytest tests/product/test_materializer.py -q
python -m casulo.product.materializer_demo `
  --output product-demos/materialized-sprint10
```

Gate focal: `5 passed`. Gate integral: `248 passed, 42 subtests passed`.
Auditoria public: `12` arquivos, zero achado privado. Nenhum benchmark
científico novo foi iniciado.
