# RFC T-0001 — Effects e capabilities deny-by-default

- Status: ACCEPTED_FOR_IMPLEMENTATION
- Data: 2026-08-11
- Compatibilidade: T 1.0 congelada; extensão explícita posterior

## Problema

O grafo histórico deriva rótulos como `read`, `guard`, `evidence` e `manifest`,
mas esses rótulos não autorizam ações. O produto precisa provar estaticamente
quais efeitos uma operação pode solicitar e validar dinamicamente cada grant.

## Vocabulário

- `effect`: descrição tipada de uma interação observável;
- `capability`: autoridade mínima, revogável e auditável para um effect;
- `request`: proposta de executar effect;
- `grant`: autorização emitida fora do modelo generativo;
- `approval`: confirmação humana ligada a evento, escopo e uso.

Conjunto inicial:

```text
pure
memory.read
memory.write
audio.capture
audio.play
model.infer
network.connect
filesystem.read
filesystem.write
process.spawn
secret.read
human.approval
manifest
```

## Regras estáticas

1. Toda operação T vNext declara seu conjunto máximo de effects.
2. Lowering calcula o fechamento de effects do corpo e falha se encontrar effect
   ausente da declaração.
3. `Any` não atravessa uma fronteira de capability sem validação/refinement.
4. Chamadas cross-module importam assinatura e effects do símbolo ligado.
5. IR e grafo preservam effects por instrução e operação.
6. `.tcap` contém requirements, policy schema e hash do contrato.
7. Um programa antigo T 1.0 continua com a semântica histórica isolada. Ele não
   ganha I/O ou grants por compatibilidade.

## Regras dinâmicas

```text
Allow(action) iff
  effect_declared
  and capability_granted
  and policy_allows_context
  and approval_satisfied_when_required
```

Ausência, corrupção, capability desconhecida ou grant expirado é `DENIED`.
Modelo, prompt, memória importada e código gerado não fabricam grants.

## Aprovação humana

Effects sensíveis podem exigir token one-shot ligado a:

```text
creation_id + capability + action_hash + source_event_id + expiry
```

O token não é secret persistido no artefato e não pode ser alargado pelo worker.

## Diagnósticos reservados

| Código | Significado |
|---|---|
| `T3100` | effect não declarado |
| `T3101` | capability desconhecida |
| `T3102` | `Any` cruza fronteira sensível |
| `T3103` | assinatura importada diverge |
| `T3104` | política/approval ausente |

## Superfície proposta, ainda não implementada

```t
language T/1.1
capability memory.read

condense Recall in Query
  effects [memory.read, manifest]
  let result = memory.lookup(query)
  emit result
```

Esta sintaxe só será adicionada junto com AST, parser, diagnósticos, lowering,
IR/grafo, golden tests, `.tcap` e migração. Nenhum parser paralelo ou sidecar
invisível é autorizado.

## Sequência de implementação

1. broker runtime independente e fail-closed;
2. congelamento verificável T 1.0;
3. AST/diagnósticos da declaração versionada;
4. lowering e checker de fechamento;
5. IR/grafo e manifesto `.tcap`;
6. goldens positivos/negativos;
7. ligação cross-module;
8. migração explícita.
