# Casulo M1 — perfil interativo rápido

Abra `START_MONDAY_DISCOVERY_FAST.vbs` por duplo clique.

Este perfil existe para descoberta humana de UX. Ele preserva:

- Qwen3-4B local e a mesma memória/continuidade T85;
- Cloud e rede guest bloqueadas;
- VM, validação, geração, simulação e materialização no fluxo `:criar`;
- eventos M1 append-only e consentimento literal de voz.

Para tornar a conversa utilizável, respostas textuais comuns não inicializam
uma VM TCG por turno. Os deltas reais do modelo são mostrados conforme chegam,
sem simular velocidade de digitação. Portanto, este perfil não substitui nem
reclassifica o release T85 selado e não é evidência de bridge VM por resposta.

O primeiro carregamento do modelo de 2,50 GB ainda pode levar alguns segundos.
Depois de `Presença local pronta · resposta incremental ativa`, o modelo fica
quente até a janela ser fechada.
