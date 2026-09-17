# RFC T-0002 — Tipos de produto T/1.1

- Status: ACCEPTED_FOR_IMPLEMENTATION
- Data: 2026-08-11
- Compatibilidade: aditivo sob `language T/1.1`; T/1.0 permanece congelada

## Objetivo

Representar contratos de produto sem esconder estruturas em dicionários livres.
O corte inicial introduz `record`, `enum` e o tipo algébrico predefinido
`Result[Ok, Error]`. Não introduz reflexão, herança ou coerção implícita.

## Sintaxe

```t
language T/1.1

record MemoryQuery
  trace text: Text

enum RecallError
  case NotFound
  case Ambiguous

condense Recall in MemoryQuery
  effects [manifest]
  emit text
```

`record` é estruturalmente fechado, ordenado e imutável neste corte. `enum`
possui casos sem payload. `Result[Ok, Error]` possui exatamente dois argumentos:
um valor de sucesso e um erro tipado. A construção/decomposição de `Result` fica
para um RFC posterior; esta etapa fecha nomes, assinaturas, IR e ABI.

## Regras

1. As três extensões exigem `language T/1.1`.
2. Nomes de tipos e casos são únicos no módulo.
3. Um record não pode ser vazio e seus campos não se repetem.
4. Um enum possui ao menos um caso e não repete casos.
5. `Result` exige exatamente dois argumentos conhecidos; não é anulável por
   coerção e não concede capability.
6. IR/grafo preservam o tipo; `.tcap` preserva somente os requisitos derivados,
   nunca grants.
7. Módulos importados expõem uma interface selada por hash; divergência é
   `T3103`.

## Diagnósticos reservados

| Código | Significado |
|---|---|
| `T3110` | tipo de produto exige T/1.1 |
| `T3111` | record inválido ou campo duplicado |
| `T3112` | enum inválido ou caso duplicado |
| `T3113` | aridade/argumento inválido de `Result` |
| `T3114` | tipo importado não resolvido |

## Migração

`field` T/1.0 continua intacto. Um `field` pode ser migrado explicitamente para
`record` em T/1.1; não há reescrita automática nem alteração do artefato legado.
