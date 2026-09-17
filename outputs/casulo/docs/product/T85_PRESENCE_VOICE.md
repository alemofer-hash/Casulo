# TS9 — Presence e voz duplex integrada

## Resultado

`TS9_PRESENCE_VOICE_SYNTHETIC_PASS` integra o `TurnCoordinator` T/2.0 ao
caminho owner e separa a presença do Guia dos workers. O gate automático
exercitou 60 minutos lógicos sem abrir microfone ou alto-falante. A avaliação
física e a qualidade subjetiva da voz permanecem reservadas a Guilherme.

## Autoridade e fluxo

- `turn-coordinator.t` decide `BARGE_IN`, `COMMIT_FINAL`, `LISTEN`,
  `SHOW_PROGRESS` ou `IGNORE`;
- um partial ASR nunca é publicado como fala final;
- progresso somente é exibido quando deriva de `JobEvent` autenticado;
- cancelamento publica `CANCELLED` e descarta conclusão tardia;
- a fila de trabalho possui um worker independente, enquanto a lane de presença
  continua respondendo;
- o launcher textual exige `COMMIT_FINAL` antes de entregar o turno ao diálogo;
- a janela humana fala respostas reais do Guia com TTS streaming first-party e
  cancela a fala ao receber nova entrada ou antes da captura do microfone;
- nenhum PCM bruto é persistido por default.

## Gate automático

O cenário sintético produziu:

- 120 turnos de áudio, cada um com partial, barge-in e final;
- 20 turnos pelo fallback textual;
- 384 `TDecisionReceipt` válidos e encadeados;
- 120 finais autorizados por T;
- 120 interrupções, com latência lógica máxima de 1 ms;
- presença disponível enquanto um worker permaneceu bloqueado;
- progresso não autenticado negado;
- resultado tardio após cancelamento não publicado;
- geração TTS formante real, porém inaudível, com cancelamento;
- frontend AEC sintético exercitado;
- 41 testes focais PASS.

Evidência selada:
`product-demos/t85-sovereign-engine/ts09-presence-voice-attempt1`.
SHA-256 do manifesto:
`52ec4ab3771656747c3ce4a63120a8a6e799fd131514e6df7c72cfed53d1bb2d`.

## Limites

O gate comprova coordenação, cancelamento, proveniência de progresso, streaming
e ausência de persistência de áudio no caminho sintético. Ele não comprova
qualidade acústica, reconhecimento pt-BR em ambiente real, AEC físico, latência
de dispositivo, química humana nem uma sessão contínua física. Esses itens
permanecem `PENDING_GUILHERME_EXPLICIT_CONSENT` e
`PROVISIONAL_OWNER_REVIEW_REQUIRED`.
