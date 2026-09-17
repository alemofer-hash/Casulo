# TS15 — reseal técnico e handoff

O release T85 final foi reconstruído a partir da fonte corrente, assinado com
chave de desenvolvimento externa ao repositório e validado fora do checkout.

## Identidade

- caminho: `release/t85-human-proof/`;
- estado do pacote: `T85_TECHNICAL_CANDIDATE_PENDING_HUMAN_PROOF`;
- manifest: `87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee`;
- SHA256SUMS: `1f897e9a9cd1e9e8bebb3d9e3ac05852e95d3655c7cfcc62cd6d2d3f12d723de`;
- assinatura: `DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE`;
- 215 arquivos e 6.374.839 bytes;
- GGUF e llama.cpp não duplicados: localizados no cache owner por hash.

O candidato técnico anterior permanece append-only em
`release/t85-human-proof-superseded-ts12-technical-candidate/`, com manifest
`f10be0ad2f7022b001e1775ba9e6e91909db48ff1960ac8d85bb51d9f338dfb3`.

## Autoridade T

A matriz congelada contém 13 superfícies e peso total 65. Dez superfícies têm
receipts causais T no release limpo. Três continuam em zero: composição geral
de tools, estado visual e recovery/update.

```text
S_authority = 56 / 65 = 0.8615384615384616
S_execution = 56 / 65 = 0.8615384615384616
C_critical  = 1.0
```

O audit de baseline sem evidência executada continua preservado com score zero.
Ele não foi sobrescrito nem usado como estado final.

## Validação

- produto integral: o relatório final contém a contagem pós-TS14;
- compilador/sistema: 73 PASS e 1 skip físico não contado;
- Cargo/Native: PASS;
- T runtime Rust release: binário reproduzido com o mesmo SHA-256 empacotado;
- appliance externo: 12/12 checks PASS, três boots, snapshot/restore e crash recovery;
- ataque final: 19 classes, P0=0, P1 suportado=0, zero efeito não autorizado;
- edições owner/public/cloud reconstruídas e assinadas separadamente;
- public audit: zero componente privado;
- Cloud: `RELEASE_LOCKED`.

O gate agregado final passou 34/34 checks. O receipt definitivo é
`product-demos/t85-sovereign-engine/ts15-reseal-attempt1/final-gate-attempt3.json`
(SHA-256 `e704540e0382549bb667e9baa1d7a9e52d4ea14b0625f48517669808322f817f`).
O diretório de evidência TS15 foi selado por manifest append-only SHA-256
`2b80a41dfa814f9920fdcbd3ac42a1b80173b35e9eb4354b5b5435d8ba4967b5`.

## Fronteiras

Cloud production, rede guest, USB/block devices e QPU continuam bloqueados.
Nenhum benchmark científico ou energético foi iniciado. A prova humana, voz
física, química, utilidade e design pertencem exclusivamente a Guilherme.
