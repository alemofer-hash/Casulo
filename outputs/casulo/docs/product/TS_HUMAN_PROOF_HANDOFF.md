# Handoff T85 para prova humana de Guilherme

## Estado

`READY_FOR_GUILHERME_CASULO_T85_VM_HUMAN_PROOF`

O estado significa que o candidato técnico passou os gates automáticos e está
pronto para avaliação humana. Não significa que voz física, química relacional,
utilidade ou design tenham sido aprovados.

## Artefato

- release: `release/t85-human-proof/`;
- launcher: `release/t85-human-proof/START_CASULO_OWNER_T85.vbs`;
- verifier: `release/t85-human-proof/VERIFY_CASULO_OWNER_T85.vbs`;
- restore: `release/t85-human-proof/RESTORE_CASULO_OWNER_T85.vbs`;
- feedback: `release/t85-human-proof/COLLECT_T85_FEEDBACK.vbs`;
- runbook: `release/t85-human-proof/T85_HUMAN_PROOF_RUNBOOK.md`;
- manifest SHA-256:
  `87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee`;
- SHA256SUMS SHA-256:
  `1f897e9a9cd1e9e8bebb3d9e3ac05852e95d3655c7cfcc62cd6d2d3f12d723de`;
- assinatura: `DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE`.

## Execução

Abra `START_CASULO_OWNER_T85.vbs` por duplo clique. Para uma verificação
read-only anterior, abra `VERIFY_CASULO_OWNER_T85.vbs`. O fluxo principal usa
`pyw.exe` e não exibe terminal.

## O que avaliar

1. naturalidade do Guia em pt-BR;
2. continuidade durante trabalho em background;
3. criação inédita com requisitos HARD explícitos;
4. recusa honesta quando falta evidência;
5. reparo, simulação e materialização;
6. `:universos`, `:rota`, `:memoria`, `:snapshot`, `:restore` e `:export`;
7. retomada após reinício;
8. qualidade de voz, barge-in, química e design.

## Fronteiras

Cloud production permanece `RELEASE_LOCKED`; rede guest `OFF`; USB e block
devices `PROHIBITED`; QPU `UNAVAILABLE_DENY`; benchmark científico
`NOT_STARTED`. Somente Guilherme pode promover ou rejeitar a prova humana.
