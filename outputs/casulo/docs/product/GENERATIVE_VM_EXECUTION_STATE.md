# Estado de execução — Casulo owner generativo na VM

- Data: 2026-08-12
- Estado: `READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION`
- Sprint atual: Sprint 10 concluído; handoff humano aberto
- Último gate aprovado: `READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION`
- Git baseline preservado: `df12e916c90d9bd2b966326275dc191573f38abd`
- Branch: `main`
- Worktree preexistente preservado: sim; nenhum reset, limpeza ou publicação

## Cenário integrado G10

A tentativa válida é `product-demos/generative-vm/sprint10-integrated-attempt12`.
Ela executou, numa única identidade de VM, os 16 passos obrigatórios: base e
overlay limpos, boot, conversa neural pt-BR, elaboração/pergunta, confirmação,
geração e reparo T, 12 estados visuais, barge-in/correção, simulação,
materialização, reboot/recall, nota, export e provas de ausência de Cloud/USB.

```text
gate = READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION
steps = 16/16 PASS
scenario_is_new = true
fake_engine_used = false
external_ai_api_used = false
scientific_benchmark = false
g10_sha256 = c698f3d649f0216b173270ca33f78617c4d8c37575a410798022243a90b9c9d6
```

As tentativas 1–11 foram preservadas. Elas revelaram e corrigiram, com
regressões, manifesto mutado, ABI UTF-8, timeout curto de CPU, conclusão sem
conteúdo visível, JSON truncado, projeto T semanticamente inválido, budget de
reparo insuficiente e testes gerativos insatisfatíveis. Nenhuma foi
reclassificada como sucesso.

## Gates aprovados

| Sprint | Gate | Evidência principal |
|---|---|---|
| 0 | baseline e fronteiras | Product Alpha confrontado; campanha científica aposentada |
| 1 | `LOCAL_STOCHASTIC_INFERENCE_PASS` | modelo local verificado, streaming, sampling e cancelamento |
| 2 | `OWNER_GENERATIVE_ENGINE_PASS` | adapter owner, contexto tipado, memória e trace |
| 3 | `SCIENCE_BROS_CONVERSATION_CONTRACT_PASS` | conversa pt-BR relacional durante jobs |
| 4 | `GENERATIVE_T_SYNTHESIS_PASS` | IntentDelta, AST T, frontend, IR, grafo, Forge e TCAP |
| 5 | `FIRST_OPEN_ENDED_AGENT_CREATED` | agente holdout reparado, simulado e materializado |
| 6 | `CASULO_VM_LIFECYCLE_PASS` | Q35/OVMF, base imutável, overlay, snapshots e restore |
| 7 | `GENERATIVE_OWNER_VM_E2E_PASS` | bridge restrito, geração, reboot e memória |
| 8 | `PROVISIONAL_STARK_JOBS_VM_PASS` | 12 estados derivados de receipts |
| 9 | `OWNER_INSPECTION_WORKBENCH_PASS` | notas, reset e feedback sanitizado |
| 10 | `READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION` | cenário integrado 16/16 |

## Validação final

```text
tests/product: 223 passed, 1 skipped in 12.45s
cargo +nightly-2026-02-01 -Z bindeps check --manifest-path os/Cargo.toml --locked: PASS
owner artifact audit: PASS; allowlist exact; zero forbidden finding
public boundary audit: PASS; 6 files; zero private component
VM doctor: PASS; base read-only; overlay; network/clipboard/shared-folder/block-device denied
free space at seal: 82.30 GiB
```

Artifact owner: `release/generative-vm/casulo-owner-generative-vm-g10-complete.zip`,
SHA-256 `bd223daf90ec64549d693fddce853cdc601d19c7c0d4c734ce90088b11fa9477`.
Selo: `release/generative-vm/handoff/MANIFEST.json`, SHA-256
`3529733742e6cd52537f1651a0488061e2f88dc4020339a450a14c57e8d69651`.
O entrypoint Python chamado pelo launcher também está selado, SHA-256
`68866f591bf6ba3a59964790d6a44fb56da08e54eb4a196871d5ef8579d4be44`.

## Modelo e execução

- Qwen3-4B Q4_K_M, Apache-2.0, SHA-256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- llama.cpp b10362, MIT, executável SHA-256
  `76008a268ba602b0a398a5d7d542a686ac279b662d97abc7eee84536d049264e`;
- sampling normal permanece estocástico e sem seed fixa;
- `--reasoning off` reserva tokens para conteúdo/JSON visível; não torna a
  geração determinística;
- inferência roda no host local por bridge first-party restrito; o guest não
  recebe rede nem pesos duplicados.

## Fronteiras e limitações

```text
cloud = RELEASE_LOCKED
public = FROZEN
usb = PROHIBITED
external_ai_api = PROHIBITED
design_status = PROVISIONAL_OWNER_REVIEW_REQUIRED
chemistry_approval = PENDING_GUILHERME_INSPECTION
voice_approval = PENDING_GUILHERME_INSPECTION
```

O handoff atual usa fallback textual pt-BR. A voz hosted existe separadamente,
mas voz duplex Native e sessão guest residente ainda não estão integradas.
Cada volta faz um boot curto. O launcher agora abre a timeline visual de 12
estados após uma criação materializada. Design, química e voz final só podem ser
aprovados por Guilherme.

## Próximo passo exato

Executar `release/CASULO_OWNER_VM_INSPECT.ps1`, conversar livremente, criar um
agente novo com `:criar`, avaliar a timeline visual, registrar fricções com
`:nota` e exportar com `:export`. Não desbloquear Cloud, public ou USB.
