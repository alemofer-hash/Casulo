# Requisitos de produto

## Fluxo principal

```text
boot -> Guia por voz -> conversa contínua -> memória orgânica
-> intenção incremental -> forma emergente -> simulação
-> correção localizada -> acordo -> materialização
```

Voz é a interface principal. Texto, mouse e terminal são fallback,
acessibilidade e modo avançado. O caminho principal não é canvas de blocos nem
prompt único seguido de output fechado.

## Invariantes

- progresso narrado deriva de eventos reais;
- eventos brutos são append-only e projeções mantêm proveniência;
- decisões rejeitadas não reaparecem como atuais;
- capabilities são deny-by-default e grants nunca vêm do modelo generativo;
- correção recompila o menor subgrafo justificável;
- simulação não possui efeitos reais;
- secrets não entram em artefatos;
- memória, permissões, voz, colaboração e exportação pertencem ao usuário;
- adaptação ocorre por preferência individual consentida, nunca por
  estereótipo;
- T descreve agentes, políticas e fluxo, sem alegar substituir pesos, drivers
  ou kernels numéricos;
- nenhuma API de IA de terceiros é requisito;
- o caminho normal não expõe token como cota criativa.

## Vertical slice hosted prioritário

1. fala pt-BR produz transcrição local streaming;
2. Guia responde por voz, continua presente com workers e aceita barge-in;
3. fala final produz `IntentDelta` e revisa `CreationSpec`;
4. Campo percorre `SILENCE`, `FIRST_INTENT`, `FIRST_FORM`, `CONFIRMATION`;
5. memória reidrata a criação e responde “lembra daquilo?” com proveniência;
6. correção preserva hashes fora do impacto;
7. simulação usa capabilities falsas;
8. materialização gera pacote Casulo e API HTTP local;
9. owner roda sem Cloud; public usa `CloudTestHarness` com progresso e
   cancelamento reais e falha honestamente quando indisponível.

## Product Alpha

Somente existe após P0–P15 passarem no Hosted Product Profile e o Native Profile
bootar reproduzivelmente, definir HAL e executar um artefato T isolado. Drivers
native completos de áudio/GPU não bloqueiam o Hosted Alpha, mas permanecem
explicitamente declarados.

## Estado de aceite em 2026-08-11

`PRODUCT_ALPHA_COMPLETE` foi atingido no Hosted Product Profile com P0-P15
aprovados. O vertical slice owner é executável, local e independente de Cloud;
o public usa exclusivamente o contrato Cloud contra o harness; o servidor
standby continua `RELEASE_LOCKED`. O Native Profile possui boot reproduzível,
HAL e execução de artefato T isolado.

O aceite não significa modelo neural generativo completo, ASR perfeito,
drivers Native completos, endpoint Cloud de produção ou release comercial. A
inteligência first-party atual é uma referência determinística, verificável e
sem dependência de API de IA de terceiros.
