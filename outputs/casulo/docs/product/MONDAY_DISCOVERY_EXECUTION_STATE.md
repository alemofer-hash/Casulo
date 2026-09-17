# Monday Discovery M1 — estado de execução

```text
STATE=READY_FOR_GUILHERME_MONDAY_DISCOVERY_SESSION
DATE=2026-08-17
HUMAN_SESSION=PENDING_GUILHERME
HUMAN_NOTES=0
PHYSICAL_VOICE_CONSENT=false
DESIGN_FINAL=NOT_STARTED
SCIENTIFIC_BENCHMARK=NOT_STARTED
```

## Baseline

- branch: `product/semantic-multiverse`;
- commit: `df12e916c90d9bd2b966326275dc191573f38abd`;
- worktree histórico: substancialmente modificado e preservado;
- release owner: `release/t85-human-proof/`;
- manifest: `87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee`;
- evidência T85: `2b80a41dfa814f9920fdcbd3ac42a1b80173b35e9eb4354b5b5435d8ba4967b5`;
- Qwen3-4B e 51/51 arquivos llama.cpp: hashes PASS;
- QEMU 11.0.50, OVMF, base VM e runtime T: PASS;
- public sem privados; Cloud `RELEASE_LOCKED`.
- checkpoint M1 append-only:
  `73d79b3c7510401a360359b826df284d95d1fa1c943cbbecea56bc8491420afe`.

## Entregue

- observer append-only com chains automática e humana separadas;
- conteúdo do usuário/transcrição não persistidos pelo observer;
- voz bloqueada até consentimento literal contemporâneo;
- métricas de presença, conteúdo, turnos, interrupções, silêncios, visual,
  falhas, materialização e reboot/recall;
- launcher M1 sem modificar o release assinado;
- roteiro humano de 2–4 horas;
- atlas inicial Markdown/JSON com nove fricções baseadas em código;
- analyzer por sessão e campanha, incapaz de declarar conclusão sem duas
  sessões e nota humana `SESSION_VERDICT`.

## Testes

- doctor read-only: 12/12 PASS;
- M1 focal: 6 PASS;
- regressão selecionada: 46 PASS, 1 skip físico por `WinError 1314` não contado;
- tentativa M1 anterior: 1 PASS, 4 setup errors por ordem incorreta de criação
  de `TMP`; preservada e substituída por execução válida, sem ocultação.

## Bloqueios conhecidos para observar

1. estado Pronto prematuro no release;
2. TTS sem consentimento literal no release;
3. ausência de troca humana de projeto;
4. namespace `active-session` fixo;
5. export repetido colide;
6. criação síncrona pode bloquear Presence;
7. visual aberto não é a timeline principal;
8. correção não está ligada ao artefato corrente;
9. stdout/stderr bruto alcança a UI.

O wrapper M1 mitiga apenas os itens necessários para inspecionar com segurança;
não reclassifica o release como corrigido.

## Próximo passo exato

Guilherme deve abrir
`product-demos/human-proof/monday-discovery-2026-08-17-attempt1/START_MONDAY_DISCOVERY.vbs`
e seguir `docs/product/MONDAY_DISCOVERY_RUNBOOK_2026-08-17.md`. Depois de duas
sessões e uma nota `SESSION_VERDICT`, execute:

```powershell
python tools/monday_discovery.py analyze-campaign --campaign-root "$env:LOCALAPPDATA\Casulo\monday-discovery\2026-08-17"
```
