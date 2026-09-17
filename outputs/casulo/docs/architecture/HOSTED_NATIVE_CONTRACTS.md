# Contratos Hosted/Native

O código de domínio conhece apenas os protocolos `Clock`, `Storage`,
`AudioCapture`, `AudioPlayback`, `DisplayDevice` e `ProcessSandbox` definidos em
`src/casulo/product/platform_contracts.py`.

O Sprint 2 entrega implementações hosted mínimas:

- relógio real do host;
- storage atômico confinado a uma raiz;
- captura sintética determinística, explicitamente rotulada como não-ASR;
- playback buffer cancelável para provar barge-in contratual;
- display textual preto/âmbar/azul orientado a estado;
- process sandbox desabilitado fail-closed.

Nenhuma dessas classes é reivindicada como driver native. O Native Profile deve
implementar os mesmos contratos atrás de sua HAL, sem introduzir chamadas do host
no domínio.

O event loop coloca `PRESENCE` antes de `FLOW`, `SYSTEM`, `BACKGROUND` e `AUDIT`.
Esta prioridade é uma propriedade testada, não uma porcentagem de progresso.
