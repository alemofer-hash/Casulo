# Gates de aceitacao do Product Alpha

Data do gate: 2026-08-11

Estado global: `PRODUCT_ALPHA_COMPLETE`

| Gate | Estado | Evidencia principal |
|---|---|---|
| P0 Auditoria | PASS | pesquisa fora do default, worktree/historico preservados |
| P1 Dominio | PASS | schemas, migracao, invariantes e serializacao canonica |
| P2 Memoria | PASS | restart, proveniencia, ambiguidade, export/delete, DPAPI |
| P3 Voz | PASS_WITH_ASR_QUALITY_RISK | ASR pt-BR, captura/playback e cancelamento fisicos; sentinela exata ainda imperfeita |
| P4 Guia | PASS | presence separada, consentimento, eventos reais, anti-bajulacao/pressao |
| P5 T/capabilities | PASS | frontend -> semantica -> IR -> graph -> TCAP, deny-by-default e quarentena |
| P6 Incrementalidade | PASS | conflito, delta local, T Forge transacional e hashes fora do impacto |
| P7 Visual | PASS | 12 estados, sem progresso decorativo, HTML/SVG local e acessivel |
| P8 Simulacao | PASS | doubles, relogio virtual, pause/resume, replay, failure injection e comparacao |
| P9 Inteligencia local | PASS_REFERENCE_FIRST_PARTY | policy/embedding locais com owner, cards, hashes e zero API externa |
| P10 Materializacao | PASS | API, round-trip, import/reedicao, sandbox, manifest/SBOM/hashes |
| P11 Installer | PASS_HOSTED_WINDOWS | doctor/plan read-only, consentimento, staging, DPAPI e sem cadastro |
| P12 Native | PASS_QEMU_OVMF_FOUNDATION | UEFI, framebuffer/serial, ring 3, syscalls, TCAP isolado e shutdown |
| P13 End-to-end | PASS_OWNER_HOSTED | demo local completa, API externa, recall e reimportacao |
| P14 Owner/public | PASS_ALPHA_DEV_SIGNED | wheels, SBOMs, manifests e chaves Ed25519 de desenvolvimento separados |
| P15 Cloud standby | PASS_STANDBY_RELEASE_LOCKED | auth/policy/jobs/replay/backpressure; producao fail-closed |

## Delimitacoes

`PRODUCT_ALPHA_COMPLETE` nao significa release publico ou producao Cloud. As
assinaturas sao de desenvolvimento e todos os manifests declaram
`production_eligible=false`. O modelo local do Guia e uma policy deterministica
first-party de referencia, nao uma alegacao de LLM proprio completo.

O gate de voz aprova o fluxo fisico e registra risco de qualidade: a frase
isolada pt-BR foi reconhecida, mas a sentinela combinada de barge-in nao teve
transcricao exata. O cancelamento por voz ocorreu e nao foi reclassificado como
precisao semantica perfeita.

Cloud permanece obrigatoriamente:

```text
release_state=RELEASE_LOCKED
production_bind=DENIED
production_eligible=false
```
