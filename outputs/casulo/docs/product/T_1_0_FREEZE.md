# Congelamento T 1.0

- Especificação: `docs/t-spec-1.0.md`
- Manifesto: `conformance/golden/manifest.json`
- Casos: 16 válidos + 26 inválidos = 42
- Hash de árvore (nome relativo NUL conteúdo, exclui manifesto):
  `3078bc4433a824d9729eaf5d00d2ad2e64849b5989a54ea1d557fa97d9f9d183`
- Data: 2026-08-11

O teste `tests/product/test_t10_freeze.py` recalcula o hash e valida todos os
casos contra os códigos diagnósticos congelados. Uma mudança exige nova versão
ou migração explícita; não é permitido atualizar o hash para esconder regressão.
