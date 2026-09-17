# ARC-6 — reparo causal e rebuild mínimo

Data: 2026-08-18  
Estado técnico: `IMPLEMENTED_AND_TESTED`  
Prova neural owner humana: `PENDING_GUILHERME`

## Resultado

O repair loop deixou de tratar `unit_id` como causalidade suficiente. No caminho
owner com `IntentTwin`, um reparo agora precisa atravessar esta cadeia:

```text
observação confirmada
  -> RequirementGraph
  -> RequirementSemanticBinding
  -> semantic_paths
  -> ForgeUnit.watch_paths
  -> StructuredDiagnostic
  -> CausalRepairPlan
  -> sementes semânticas + dependentes transitivos
  -> TForge incremental
  -> CausalRepairReceipt
```

O modelo neural continua podendo propor a revisão textual da unidade. Ele não
decide quais requisitos, caminhos ou unidades podem ser alterados.

## Contratos

`casulo.product.causal_repair` fornece:

- `RequirementSemanticBinding`: vínculo tipado entre requisito confirmado,
  caminhos semânticos, verificadores, proveniência e unidades T;
- `bind_intent_requirements`: deriva os vínculos do `IntentTwin` confirmado e
  recusa requisito HARD sem unidade T;
- `CausalRepairPlanner`: recusa diagnóstico sem requisito causal e calcula o
  menor fechamento seguro de unidades que observam o caminho mais seus
  dependentes;
- `CausalRepairReceipt`: confere o plano contra o `ForgeReceipt`, prova hashes
  preservados fora do subgrafo e sela TCAP antes/depois.

No `VerifierRepairLoop`, `require_causal_repairs=True` é fail-closed. Essa opção
é ativada pelo worker owner sempre que existe `IntentTwin`. Rotas históricas sem
o contrato continuam reprodutíveis, mas não recebem a alegação causal.

## Síntese fail-closed

O prompt de síntese recebe o brief confirmado e os caminhos de cada requisito.
Depois do frontend, IR e grafo T passarem, o candidato ainda precisa mapear todo
requisito HARD a ao menos uma unidade. Candidato desconectado é rejeitado e uma
nova tentativa pode ocorrer apenas dentro do budget preexistente.

Nenhuma sintaxe T foi adicionada neste sprint.

## Evidência

O smoke append-only válido está em:

`product-demos/human-proof/arc-causal-repair-2026-08-18-attempt2`

Resultado:

- requisito causal: `req:twin:arc6-smoke:obs:approval`;
- caminho: `behavior.approval`;
- unidade alterada: `review`;
- rebuild: `review`, `output`;
- reuse byte-identical: `decision`, `identity`;
- quatro execuções externas T: PASS;
- TCAP anterior:
  `5cb80b2c52725fdcda6f26b62d83a81d387caf365ee2fdb4b6700152cf55c2b7`;
- TCAP posterior:
  `0b4f14a39cee55edd54ae890f209f3af5fd028995c6748c0181e8e9014f2ecdd`;
- receipt causal:
  `024769806232a940505c97e4a9761259555e33efd6cbc12893c285a159ba0645`;
- manifest:
  `de8f35589fce1a62f266289748dde3f680b0c55355873ec923cf8fb85c5215e7`.

O `attempt1` foi preservado com `ERRATA.md`: ele usou hashes de `ForgeReceipt`
em campos nomeados como TCAP. Não sustenta identidade TCAP e foi superseded pelo
`attempt2`.

## Gates executados

```text
22 focused tests passed
482 product tests passed, 1 skipped
compileall PASS
contract smoke PASS
```

O smoke é classificado explicitamente como
`DETERMINISTIC_CONTRACT_SMOKE_NOT_OWNER_NEURAL_PROOF`. Não houve benchmark,
API externa, Cloud, USB ou prova humana simulada.

## Limite e próximo passo

ARC-6 prova o mecanismo causal e seu uso no código owner. A qualidade da revisão
proposta pelo Qwen em uma criação inédita, a confirmação de Guilherme e a
materialização visual continuam pendentes da sessão humana.

O próximo sprint de engenharia é ARC-7: orçamento neural por rota, com contexto
suficiente mínimo e sem reduzir gates semânticos.
