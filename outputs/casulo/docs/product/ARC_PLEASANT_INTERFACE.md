# ARC-9 — presença contínua e interface agradável

Data: 2026-08-18  
Estado: `IMPLEMENTADO_TESTADO; HUMAN_UX_PROOF_PENDENTE`

## Contrato

ARC-9 separa a superfície visual do texto incidental do processo. O owner emite
eventos JSONL tipados e a interface consome somente eventos validados:

```text
PRESENCE_READY / MODEL_LOADING / MODEL_READY
ASSISTANT_START -> ASSISTANT_TOKEN* -> ASSISTANT_END
JOB_STARTED -> JOB_MILESTONE* -> JOB_COMPLETED | JOB_FAILED | JOB_CANCELLED
```

`PRESENCE_READY` significa que a janela aceita e preserva entrada; não significa
que o modelo já terminou de carregar. `MODEL_READY` fecha essa distinção.
Tokens aparecem quando o runtime os produz. Não há temporizador que simule
digitação sobre uma resposta já pronta.

## Progresso honesto

Um milestone de criação só é publicável quando possui evidência concreta e
hash: `IntentDelta`, `RequirementGraph`, projeto T, TCAP, simulação,
materialização ou round-trip. Porcentagens, ETA e progresso fabricado são
proibidos pelo validador. A conclusão tardia de um job cancelado permanece
`JOB_CANCELLED` e não pode publicar criação viva.

O trabalho após `CONFIRMO` roda fora do loop de conversa. A superfície continua
aceitando comandos, texto e `:cancelar`. Enquanto o worker ocupa o runtime
neural, a resposta de presença descreve apenas o último receipt real; diálogo
neural livre concorrente ainda não é prometido neste slice.

## Superfície

A janela owner foi reduzida a conversa, forma central viva, campo de entrada e
ações primárias `Criar algo` e `Falar`. Snapshot, restore, universos, rota,
memória, exportação e notas ficam atrás de `Mais`. Voz continua opt-in literal;
TTS só começa depois de `ASSISTANT_END` completo.

O observador persiste timestamps, tipos e hashes, mas não tokens da resposta nem
conteúdo do usuário. Cloud permanece `RELEASE_LOCKED`; nenhuma API externa foi
introduzida.

## Implementação e prova

- protocolo: `src/casulo/product/pleasant_interface.py`;
- streaming neural: `tools/casulo_owner_vm_inspect.py`;
- job owner e receipts: `private/casulo-owner/src/casulo_owner/generative_agent_probe.py`;
- coordenação: `tools/casulo_semantic_multiverse_vm_inspect.py`;
- interface: `tools/monday_discovery_session.pyw`;
- gate: `tools/arc_pleasant_gate.py`;
- evidência: `product-demos/human-proof/arc-pleasant-interface-2026-08-18-attempt2`;
- launcher humano: `product-demos/human-proof/monday-arc-pleasant-2026-08-18-attempt1/START_CASULO_ARC9.vbs`.

O manifest da evidência possui SHA-256
`e093a3d739e2ad0d370e3334e9c9a7b70a0750f3fdee6650caecba500a4ce3d1`.
A classificação é
`DETERMINISTIC_UX_CONTRACT_SMOKE_NOT_OWNER_NEURAL_HUMAN_PROOF`.
O `attempt1` permanece append-only e foi superseded porque antecede a correção
que impede um `ASSISTANT_END` falho de ser contado como resposta substantiva.

## Limites

Não foram aprovados neste gate: química relacional, beleza, qualidade neural,
latência percebida sob uma conversa longa, microfone, alto-falante ou barge-in
físicos. O modo host-direct usa o checkout corrente e não substitui o release
owner selado. ARC-10 convergiu o protocolo e o event loop para o guest Native;
modelo, voz física, memória DPAPI, renderer e materialização permanecem Hosted.
