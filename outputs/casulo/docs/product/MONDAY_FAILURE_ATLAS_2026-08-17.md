# Atlas de falhas de segunda-feira — 17/08/2026

## Estado

`READY_FOR_GUILHERME_MONDAY_DISCOVERY_SESSION`

Este é o atlas inicial, anterior à sessão humana. Ele contém somente fatos de
preflight, inspeção de código e riscos explicitamente marcados. A lista de
opiniões humanas está vazia; nenhum juízo foi atribuído a Guilherme.

Baseline preservado: `READY_FOR_GUILHERME_CASULO_T85_VM_HUMAN_PROOF`, commit
`df12e916c90d9bd2b966326275dc191573f38abd`, release manifest
`87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee`.

## Preflight read-only

- assinatura, manifest e 212 entradas do payload: PASS;
- Qwen3-4B Q4_K_M: 2.497.280.256 bytes e SHA-256 esperado: PASS;
- árvore llama.cpp: 51/51 arquivos: PASS;
- QEMU 11.0.50, qemu-img e OVMF: PASS;
- base VM e runtime T: hashes PASS;
- public: zero componente privado; Cloud: `RELEASE_LOCKED`;
- 46 testes selecionados PASS;
- 1 skip de symlink físico por `WinError 1314`, não contado como PASS;
- voz física aberta: não;
- benchmark científico/energético iniciado: não;
- espaço no início: 78.822.363.136 bytes livres.

A primeira tentativa dos cinco testes M1 teve 1 PASS e quatro erros de setup
porque o diretório `TMP` foi resolvido antes de ser criado. O XML falho foi
preservado. A tentativa corrigida teve 5/5 PASS.

## Como a observação funciona

O launcher M1 carrega o aplicativo do release assinado, sem alterá-lo. A camada
externa registra apenas hashes, comprimentos, relógios, estados e marcadores em
`automated-events.jsonl`. Texto do usuário e transcrições não são persistidos
pelo observer. Notas digitadas conscientemente ficam em `human-notes.jsonl`,
com proveniência `HUMAN_OPINION_GUILHERME`, numa hash chain distinta.

TTS e microfone permanecem bloqueados até Guilherme digitar literalmente:

```text
AUTORIZO VOZ LOCAL POR 8 SEGUNDOS SEM SALVAR PCM
```

Esse consentimento vale somente para a sessão corrente. PCM bruto não é salvo.

## Fricções confirmadas antes da sessão

| ID | Severidade | Fricção | Camada | Estado |
|---|---:|---|---|---|
| M1-F001 | P2 | UI anuncia Pronto após spawn, antes do header real | Presence/UI | mitigada só no observer |
| M1-F002 | P1 | TTS do release não exige consentimento literal da sessão | Voice/Consent | bloqueada só no observer |
| M1-F003 | P1 | project ID é fixo; não há troca A/B humana | Living Memory/UI | aberta |
| M1-F004 | P1 | `active-session` é reutilizado | Inspection Recorder | mitigada só no observer |
| M1-F005 | P2 | segundo `:export` colide com destino existente | Inspection Export | aberta |
| M1-F006 | P1 | `run_probe` síncrono ocupa o loop humano | Presence/Jobs | confirmação humana pendente |
| M1-F007 | P2 | browser abre mapa semântico, não a timeline da criação | Creation Field | aberta |
| M1-F008 | P1 | conversa de correção não está ligada ao artefato atual | Intent/T Forge | aberta |
| M1-F009 | P2 | stderr bruto compartilha canal com UI | Process/UI | risco monitorado |

O JSON equivalente contém, para cada item, evidência, reprodução, impacto,
teste ausente e correção mínima plausível.

## Instrumentação mensurada

- tempo entre launcher e primeiro output;
- tempo até `PRESENCE_READY` real;
- tempo até primeira resposta substantiva;
- turnos por hash/comprimento, sem conteúdo;
- interrupções durante TTS;
- silêncios de 10 e 30 segundos;
- reboot/recall reportado;
- materialização, rota, visual e estados visitados;
- tracebacks, infraestrutura exposta e falhas recuperáveis;
- notas humanas em canal separado;
- integridade de ambas as hash chains.

## Condição para completar o atlas

`MONDAY_FAILURE_ATLAS_COMPLETE` só pode ser emitido depois de:

1. pelo menos duas sessões M1, antes e depois do reboot;
2. chains automáticas e humanas válidas;
3. uma nota explícita de categoria `SESSION_VERDICT` escrita por Guilherme;
4. incorporação das notas sem convertê-las em diagnóstico automático.

Até lá, design final permanece fora de escopo.
