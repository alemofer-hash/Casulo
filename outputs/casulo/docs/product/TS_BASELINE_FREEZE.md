# TS0 — congelamento do baseline T85

Data: 2026-08-14T21:22:00-03:00  
Estado: `TS0_BASELINE_FROZEN`

## Identidade preservada

- branch: `product/semantic-multiverse`;
- commit: `df12e916c90d9bd2b966326275dc191573f38abd`;
- worktree preexistente: 19.802 entradas no início efetivo do TS0;
- SHA-256 do snapshot porcelain: `c5d8cf3b99fa6a158c357f116e2e5286af1faf861906dc25b9cc1709035457b7`;
- espaço livre: 83.413.475.328 bytes, 77,68 GiB;
- release histórico: `release/human-proof/`, preservado e nunca sobrescrito.

Hashes RC13 preservados:

- `release/human-proof/MANIFEST.json`: `b6bfaa8166b0b2174392be64c1936a266e8a8cd119c9c7a8ab5e38017c2c4196`;
- `release/human-proof/SHA256SUMS`: `b5c820b66b24b30a07265b7182f1c5f684233c0f9cbb86d2ba511239c01ad42c`;
- pacote owner: `547cc4047b5d7523dae28960dbaa67971bdf952ece4a9e7b2a9f14a9104f6a9a`;
- imagem Native: `74fe4b1130b40f5090c9944acdd4da0b86c122ab99be5a6b314f61a7e22b810b`;
- gate RC13 reseal: `2d2de97b0d0d574a18d99274b9080d212dd159930dc552d821eba98332273c79`.

## Pacote vinculante

ZIP recebido: SHA-256
`0359c78274d74017cd8279abaa849e8e46ecfed5d71fa5685d8fd35217f21140`.
As 23 entradas cobertas por `MANIFEST.sha256` conferiram integralmente. O ZIP
não continha caminho absoluto ou traversal. A extração foi feita em namespace
novo sob `work/goal-staging/`.

O baseline empacotado tem SHA-256
`415ea4a817bddfe6e845a5b12cc56e086de7b238ddc73d658c8d662c9f2c1b1e`.
O relatório local tem SHA-256
`a0addf60a073162d3e1881fe8ebdbc66e4b4ebc912048033d2e1456d7a1d4f14`.
Os bytes diferem exclusivamente por CRLF versus LF: após normalização para LF,
os 92.447 caracteres são idênticos. Isso não é divergência semântica.

## Reconciliação de soberania

Três objetos históricos permanecem distintos:

1. `docs/product/RC_T_SOVEREIGNTY_MATRIX.json`: preregistro RC com 11
   superfícies, peso total 36 e degrees `null`;
2. `src/casulo/t/sovereignty.py`: audit executado com 9 superfícies, peso total
   27;
3. `product-demos/revolution-closure/rc04-t-sovereignty/t-sovereignty-audit.json`:
   score histórico 1,0 sobre essas 9 superfícies estreitas.

O T85 adota prospectivamente 13 superfícies e peso total 65 em
`docs/product/TS_SOVEREIGNTY_MATRIX.json`. O score RC4 continua válido somente
no escopo em que foi medido. Não é renomeado, recalculado retroativamente nem
usado como baseline global T85.

## P0 herdados

1. release depende do checkout e `PYTHONPATH`;
2. T gerado usa semântica estreita e TCAP produtivo pode ser apenas `RET`;
3. LivingMemory/Guide completo não está ligado ao launcher;
4. TTS de respostas não está ligado à GUI.

Fronteiras congeladas: Cloud `RELEASE_LOCKED`, guest network `OFF`, USB/block
devices `PROHIBITED`, QPU `UNAVAILABLE_DENY`, benchmark científico
`NOT_STARTED`, assinatura `DEVELOPMENT_NOT_COMMERCIAL` e aprovação humana
`GUILHERME_ONLY`.

