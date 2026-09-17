# TS10 — Semantic Multiverse físico

## Resultado

`TS10_PHYSICAL_SEMANTIC_MULTIVERSE_PASS` materializa os seis universos como
bundles compactos content-addressed e usa `mmap` somente leitura, cache parseado,
leases e reclaim real. A policy T/2.0 decide `ACTIVATE` e `HIBERNATE`; a
primitive Python apenas executa a decisão e produz receipt físico encadeado.

## Bundle e lifecycle

Cada `UniverseBundle` referencia exatamente nove classes de ativos:
manifesto, binding T/TCAP, schemas, verificadores, índice de recuperação,
ferramentas, sufficient state, probes e proveniência. Objetos idênticos são
deduplicados por SHA-256. Nenhum arquivo de padding foi criado.

O fluxo observado é:

```text
FROZEN -> WARMING -> WARM -> ACTIVATING -> HOT
HOT -> HIBERNATING -> FROZEN
```

O fechamento de um universo HOT exige decisão T, ausência de lease, residência
mínima e sufficient state com os cinco invariantes críticos. Corrupção,
capability amplification, rota não confiável e cancelamento falham antes do
`mmap`.

## Comparação pré-registrada

Perfis executados sobre dois projetos e seis intenções por projeto:

- `REFERENCE_SIMPLE_RETRIEVAL`;
- `ALL_HOT`;
- `T_SPARSE_MULTIVERSE`.

Resultados:

- campos críticos comparados: 180/180;
- `L_critical = 0`;
- project bleed: 0;
- pico `ALL_HOT`: 28.642 bytes gerenciados;
- pico `T_SPARSE_MULTIVERSE`: 5.342 bytes gerenciados;
- `R_managed = 0,18650932197472245`;
- mapped/cache bytes após reclaim: 0/0 nos dois modos;
- 10 transições sufficient-state descartaram apenas cache local não crítico;
- 36 receipts T e 36 receipts da primitive, quatro cadeias válidas;
- model calls: 0;
- 19 testes focais PASS.

Evidência final selada:
`product-demos/t85-sovereign-engine/ts10-physical-multiverse-attempt5`.
SHA-256 do manifesto:
`65dc705a9e6bce06d51ccf0e868ae2953af48272293ed6886638c5968dcb906f`.

O attempt3 permanece preservado como `TS10_FAIL`: a unidade de entrada já era
mínima e, portanto, não demonstrava redução de bytes na projeção. O attempt4
passou antes da auditoria independente das cadeias; o attempt5 o supersede como
evidência final.

## Limites

`R_managed` cobre exclusivamente arquivos mapeados e caches parseados dos
bundles de universo. O RSS total foi publicado, mas não recebe target porque
Python, runtime T e outras bases fixas dominam o processo. Qwen3-4B e llama.cpp
estão explicitamente fora do conjunto gerenciado. Este gate não mede energia,
velocidade geral nem paginação dos pesos do modelo.
