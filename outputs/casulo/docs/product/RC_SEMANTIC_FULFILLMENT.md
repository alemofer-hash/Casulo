# RC3 — Fulfillment semântico verificável

Estado: `RC3_SEMANTIC_FULFILLMENT_PASS`.

O `RequirementGraph` separa requisitos `HARD`/`SOFT`, `PASS`/`FAIL`/`UNKNOWN`
e só aceita receipts de verificadores independentes. Compilar ou o gerador
afirmar que terminou nunca constitui evidência. Cinco `DomainPack`s cobrem
computação científica, fluxo administrativo, trânsito de dados, ferramenta
criativa interativa e serviço local.

O ensaio neural usa Qwen3-4B Q4_K_M local, sampling normal e schemas fechados.
As tentativas 1–3 falharam e permanecem preservadas. A tentativa 4 passou
5/5 famílias. O reparo recebeu diagnostics reais; não houve fixture, fake ou
API externa.

Na família científica, uma declaração tipada como
`levi_civita: tensor[...]` agora satisfaz o identificador canônico sem permitir
substring arbitrária. Ainda são obrigatórios residual explícito, escopo local
e recusa de solver PDE global.

Evidência canônica:

- `product-demos/revolution-closure/rc03-fulfillment/gate.json`;
- `product-demos/revolution-closure/rc03-fulfillment/neural-holdout-attempt4/semantic-fulfillment-holdout.json`.

O gate não autoriza alegar completude de produção nem solver científico geral.

