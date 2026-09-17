# T v2 — especificação semântica mínima

Status: `TS2_DRAFT_IMPLEMENTED`  
Versão: `T/2.0`

## Objetivo e compatibilidade

T/2.0 é um control-plane verificável para agentes Casulo. T/1.0 e T/1.1
continuam aceitos pelo frontend histórico e não são reinterpretados. Um arquivo
T/2.0 usa o frontend v2 explícito; não existe detecção ambígua.

## Forma lexical

UTF-8, indentação por dois espaços, comentários iniciados por `#`, identifiers
ASCII `[A-Za-z_][A-Za-z0-9_]*` e literais JSON em uma linha. O header é:

```text
language T/2.0
module owner.publish
budget steps 4096
capability manifest
```

## Tipos

Primitivos: `Bool`, `Int`, `Float`, `Decimal`, `Text`, `Bytes`, `Timestamp`.
Tipos compostos: records, enums, `Option<T>`, `Result<T,E>`, `List<T,N>`,
`Map<K,V,N>` e `Set<T,N>`. Toda coleção tem limite positivo no tipo. IDs de
session/project/creation/capability/receipt são records opacos da stdlib.

## Declarações

```text
record PublishInput
  member confirmed: Bool
  member hard_statuses: List<Text,64>

enum PublishDecision
  case PUBLISH
  case BLOCKED

state attempts: Int = 0

fn decide(input: PublishInput) -> Result<Text,Text>
  effects [manifest]
  requires input.confirmed else "intent_unconfirmed"
  for status in input.hard_statuses limit 64
    requires status == "PASS" else "hard_requirement_not_pass"
  return ok "PUBLISH"
```

Funções têm parâmetros e retorno explícitos. Locals são imutáveis; `state`
requer `set state.nome = expressão`. `if/else`, `match` e `for ... limit N`
são estruturados. `return ok/error` constrói `Result`. `request effect` apenas
produz pedido tipado; um handle não forjável precisa ser ligado pelo runtime.
`spawn`, `join` e `cancel if` representam jobs estruturados e possuem pontos de
cancelamento.

## Expressões

Literais JSON, referências locais/fields, `not`, comparações, `and`, `or` e
built-ins puros allowlisted (`len`, `all_equal`, `contains`, `add`, `get`).
Não há eval, import dinâmico, filesystem, rede, processo ou path.

## Contracts e limites

- `requires expr else error` retorna `Err(error)` antes de qualquer effect;
- `ensures expr else error` valida o resultado antes do commit;
- loops exigem limite literal positivo e também obedecem ao budget global;
- toda função tem retorno em todos os caminhos ou diagnostic;
- pattern matching deve ser exaustivo sobre enum/Result/Option;
- effect usado precisa estar no header e na função;
- cancel/deadline/resource exhaustion são valores tipados, não exceções ocultas.

## Serialização

Objetos de entrada, estado, saída, diagnostic e receipt usam JSON UTF-8
canônico: chaves ordenadas, sem whitespace e sem NaN/Infinity. Schema e module
graph participam da identidade do TCAP.

## Segurança

Output neural é apenas source. O pipeline obrigatório é parser → type/effect
checker → boundedness → capability linker → IR → verifier → TCAP. Falha é
fail-closed. T/2.0 nunca transforma texto do modelo em grant, assinatura ou
aprovação humana.

