# Evidência — Sprint 2 da VM generativa

## Resultado

`OWNER_GENERATIVE_ENGINE_PASS`

## Implementação

- `OwnerGenerativeEngineAdapter` implementa `CasuloEngine` diretamente;
- `EngineEventKind.TOKEN` transporta fragments neurais reais;
- `ContextAssembler` inclui todas as constraints duras ou falha fechado;
- memórias importadas são delimitadas como não confiáveis;
- o store de contexto é one-shot e valida SHA-256;
- `StochasticTrace` é persistido append-only, sem conteúdo bruto da resposta;
- cancelamento produz terminal `CANCELLED` e não produz consolidação.

## Demo neural multivolta

Três turnos executaram no Qwen3-4B local. O contexto evoluiu em cada turno,
todos os streams tiveram múltiplos fragments e o último turno recuperou a
decisão de não enviar, publicar ou alterar nada sem confirmação humana.

- evidência:
  `product-demos/generative-vm/sprint2/g2-owner-generative-engine.json`;
- SHA-256:
  `d308c812cca499e571317f7f9df31eebdcaa0b203844776c8be4f3234634794c`;
- traces SHA-256:
  `20cd2688b8f8c09c261133ec92cabbe0021f5204ced6dcd4246d34c2894fff74`.

## Fronteira do artifact owner

O artifact do Sprint 2 foi construído por allowlist exata. Ele contém o adapter
generativo, runtime/registro/contexto e o manifesto pinado do candidato. Não
contém `LocalGuidePolicy`, `LocalOwnerMotor`, `OwnerEngineAdapter`,
`DeterministicFakeEngine`, `CloudEngineClient`, peso ou SDK comercial.

- artifact:
  `product-demos/generative-vm/sprint2/casulo-owner-generative-s2.zip`;
- SHA-256:
  `22b4857605893db8c94a3b5ecee823db32861241508b1debb41817021c74d6e7`;
- auditoria:
  `product-demos/generative-vm/sprint2/owner-artifact-audit.json`;
- `allowlist_exact=true`, `reference_engine_absent=true`.

## Limite

G2 prova engine owner generativo local no Hosted Profile. A qualidade relacional
G3, síntese T, reparo, VM e aprovação humana permanecem abertos.
