# Evidência — Sprint 4 da VM generativa

## Resultado

`GENERATIVE_T_SYNTHESIS_PASS`

## Fluxo comprovado

```text
fala inédita
-> inferência neural local
-> IntentDelta.PROPOSED
-> confirmação humana separada
-> CreationSpec
-> AST T generativa
-> lowering T/1.1
-> frontend
-> semantics
-> IR
-> graph
-> Forge incremental
-> TCAP parseável
```

O agente “Farol de Decisões” recebeu 9 operações de intenção, 4 unidades T e 4
testes comportamentais gerados. A correção mudou apenas `identity_unit`; as
outras três unidades foram reutilizadas com hashes de source idênticos.

## Invariantes

- inferência só pode produzir `PROPOSED`;
- confirmação é evento humano externo ao modelo;
- capability request não é grant;
- AST neural não controla sintaxe, lowering ou topologia de build;
- source diff precisa intersectar affected paths;
- TCAP carrega requirements, nunca grants;
- caminho legado de training não foi usado.

## Falhas preservadas

As sete tentativas anteriores estão em diretórios separados. Cada falha levou a
um teste ou a uma redução de autoridade neural: `/no_think`, schema de source,
`source_lines`, limite de resposta, posições sintáticas, AST tipada e topologia
acíclica derivada. Nenhum resultado parcial foi promovido.

## Artefatos

- evidência:
  `product-demos/generative-vm/sprint4-attempt8/g4-generative-t-synthesis.json`;
- SHA-256:
  `a481f02cd38e8fd3090f064e8f6667463593d9a41bb2f23bd74a720f728730e2`;
- sources/tests/TCAP:
  `product-demos/generative-vm/sprint4-attempt8/initial`;
- correção incremental:
  `product-demos/generative-vm/sprint4-attempt8/corrected`;
- artifact owner allowlisted SHA-256:
  `e26bdfbdea98f5d472632f16ae2682ea8742736f379cc0f4d297c55950d6396f`.

## Limite

G4 não prova reparo por diagnostic, simulação comportamental completa nem agente
materializado rodando fora do processo de criação. Esses são os gates do Sprint
5.
