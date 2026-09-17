# TS8 — GuideContinuity e LivingMemory no caminho owner

## Resultado

`TS8_GUIDE_LIVING_MEMORY_PASS` integra o launcher Semantic Multiverse ao estado
canônico do Guia e à memória cifrada. A lista Python de conversa permanece
somente no fallback legado; quando o serviço TS8 está presente, o contexto vem
de `GuideContinuityKernel`, é autorizado pela policy T e cada turno é
journalizado na `LivingMemory`.

## Propriedades comprovadas

- lease single-writer de processo, fail-closed;
- um arquivo atômico DPAPI por evento e hash chain append-only;
- detrito de escrita interrompida preservado e excluído da cadeia canônica;
- restauração do kernel exclusivamente pelo journal cifrado;
- escopos de projeto separados no search/recall;
- constraints, rejeições, conflitos e supersession não são sobrescritos;
- conflito produz `ASK_HUMAN` por decisão T;
- contexto normal produz `SELECT` por decisão T;
- receipts T persistidos e encadeados através de reboot;
- compactação cria snapshot cifrado e receipt sem apagar eventos;
- delete exige a frase de consentimento exata;
- `trainable=false` por default;
- launcher owner usa `DpapiSecretBox` e registra cada turno.

## Gate sintético

O cenário usou três projetos (`flood-rs`, `einstein-local`, `voice-studio`) e
500 turnos. Resultado:

- 500/500 decisões normais T `SELECT`;
- 1 decisão de conflito T `ASK_HUMAN`;
- 501 `TDecisionReceipt` encadeados;
- 515 eventos de continuidade cifrados;
- 4 reboots intermediários e 1 reboot final com estado idêntico;
- perda de constraints HARD: 0;
- project bleed: 0;
- recall sem pista: `AMBIGUOUS` nos três projetos;
- plaintext de controle ausente dos envelopes DPAPI;
- 50 testes focais PASS.

Evidência selada:
`product-demos/t85-sovereign-engine/ts08-guide-memory-attempt1`.
SHA-256 do manifesto:
`70eb6ac250d0568040e3c1178139bcb544c9a08141f294d7ad5c18af77b90baa`.

## Limitação observada

`LivingMemory.append` ainda reconstrói todas as projeções após cada evento. O
gate de 500 turnos tornou o custo crescente visível. Isso não afetou
integridade, memória residente ou resultado, mas é dívida de latência e deve ser
otimizado causalmente em sprint posterior sem reclassificar esta coleta.

Nenhuma voz física, química humana ou inferência neural longa foi avaliada no
TS8.
