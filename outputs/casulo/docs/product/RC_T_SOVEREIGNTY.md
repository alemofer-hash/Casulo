# RC4 — Soberania T

Os pesos de soberania foram congelados no RC1 e não foram alterados. Nove
superfícies de decisão possuem contratos T/1.1 executáveis:

1. intenção e requisitos;
2. lógica do agente;
3. tools e composição;
4. memória;
5. jobs e cancelamento;
6. effects e capabilities;
7. interfaces;
8. teste e simulação;
9. materialização.

Cada receipt de superfície contém hashes da fonte, IR, grafo e artefato, além
da operação e decisão efetivamente executadas. As rotas críticas são
fail-closed. Mudanças localizadas continuam content-addressed por artefato.

As fronteiras Python de referência, llama.cpp e Casulo Native estão tipadas em
`ForeignBoundaryManifest`; T governa decisões de produto, mas não substitui
pesos, drivers, runtimes ou kernels.

Evidência canônica após o gate:

- `product-demos/revolution-closure/rc04-t-sovereignty/t-sovereignty-audit.json`;
- `product-demos/revolution-closure/rc04-t-sovereignty/foreign-boundaries.json`;
- `product-demos/revolution-closure/rc04-t-sovereignty/gate.json`.

