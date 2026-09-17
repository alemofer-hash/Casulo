# Evidência — Sprint 7 Intent Engine e T Forge incremental

Data: 2026-08-11

Estado: `SPRINT_7_INTENT_T_FORGE_PASS`

## Slice

O caminho executável agora é:

```text
VoiceEvent final
-> gramática conservadora de intenção
-> IntentDelta PROPOSED
-> confirmação humana explícita
-> CreationSpec candidata isolada
-> T frontend / AST / análise / IR / grafo
-> commit incremental
-> FIRST_FORM
```

Ambiguidade não gera delta. Proposta não altera conteúdo. Rejeição fica
registrada sem compilação. Se qualquer unidade T reprovar, a criação viva e o
cache anterior permanecem intactos.

## Demonstração

Fala sintética do harness:

```text
defina behavior.tone como direto
confirmo
```

Resultado:

- `proposal_did_not_mutate_content=true`;
- estado final `FIRST_FORM`;
- `behavior.tone=direto`;
- recompiladas: `behavior`, `interface`;
- reutilizada: `identity`;
- hash preservado de `identity`:
  `0c6ebe9365c65571ee9fea79fe08c88a4015b2d174070e518e6d99b0fb789373`;
- receipt: `casulo.t-forge-receipt/1.0`.

O Forge não usa o caminho legado `parse_training_spec -> _render_training_c` e
não introduz sintaxe T. Cada unidade passa por `check_source`, incluindo parser,
análise semântica, IR geral e Metamorfose Graph.

## Comandos

```powershell
python -m pytest tests/product/test_intent_forge.py -q
python -m casulo.product.intent_forge_demo `
  --utterance "defina behavior.tone como direto"
```

O primeiro gate focal passou com `10 passed`. Nenhum benchmark científico novo
foi iniciado.
