# Linguagem T 1.0 — Núcleo executável do Casulo

**Status:** núcleo congelado; runtime de referência disponível
**Implementação de referência:** `casulo.t`  
**Marca e origem:** Teloscorp / Casulo

## 1. Finalidade

T descreve transformação conservativa de informação por meio de estruturas,
restrições, estabilização e emissão explícitas.

T 1.0 é deliberadamente pequena. Extensões científicas, arrays e fases do
FLOOD-RS serão adicionados por versões ou features declaradas, sem redefinir
silenciosamente este núcleo.

## 2. Codificação e layout

- arquivos UTF-8;
- extensão `.t`;
- indentação significativa;
- dois espaços por nível;
- tabs proibidos na indentação;
- identificadores ASCII nesta versão;
- comentários começam com `#` fora de strings;
- uma instrução por linha.

## 3. Gramática

```bnf
program         ::= module_decl? use_decl* top_decl*
module_decl     ::= "module" qualified_name NEWLINE
use_decl        ::= "use" qualified_name NEWLINE

top_decl        ::= field_decl
                  | condense_decl
                  | transition_decl

field_decl      ::= "field" TypeName NEWLINE INDENT trace_decl+ DEDENT
trace_decl      ::= "trace" name ":" type_expr NEWLINE

condense_decl   ::= "condense" TypeName ("in" TypeName)?
                    NEWLINE INDENT stmt+ DEDENT

transition_decl ::= "transition" TypeName NEWLINE
                    INDENT
                    "from" TypeName NEWLINE
                    "to" TypeName NEWLINE
                    stmt+
                    DEDENT

stmt            ::= let_stmt
                  | project_stmt
                  | bind_stmt
                  | restrict_stmt
                  | judge_stmt
                  | stabilize_stmt
                  | emit_stmt
                  | if_stmt

let_stmt        ::= "let" name "=" expr NEWLINE
project_stmt    ::= "project" expr ("as" TypeName | "into" name_list)? NEWLINE
bind_stmt       ::= "bind" expr "with" expr NEWLINE
restrict_stmt   ::= "restrict" expr NEWLINE
judge_stmt      ::= "judge" expr NEWLINE
stabilize_stmt  ::= "stabilize" expr NEWLINE
emit_stmt       ::= "emit" expr NEWLINE
if_stmt         ::= "if" expr NEWLINE INDENT stmt+ DEDENT
                    ("else" NEWLINE INDENT stmt+ DEDENT)?

name_list       ::= name ("," name)*
type_expr       ::= primitive | TypeName | type_expr "?" | "[" type_expr "]"
```

## 4. Tipos congelados

- `Text`
- `Number`
- `Bool`
- `Time`
- `Date`
- `Duration`
- `Any`
- `T?`
- `[T]`

Tipos definidos por `field` podem ser utilizados por outros fields e por
operações.

## 5. Declarações

### `module`

Identifica o programa:

```text
module casulo.flood_rs
```

Quando presente, precisa ser a primeira declaração.

### `use`

Declara dependência qualificada:

```text
use casulo.std.math
```

Nesta sprint, `use` é representado na AST; resolução entre módulos será
implementada em marco posterior.

### `field` e `trace`

Definem uma estrutura:

```text
field HydroCell
  trace precipitation: Number
  trace storage: Number?
  trace history: [Number]
```

Um field precisa conter ao menos um trace. Nomes de trace não podem se repetir.

### `condense`

Transforma e emite informação:

```text
condense WaterBalance in HydroCell
  judge precipitation >= 0
  let delta = precipitation - evapotranspiration
  stabilize delta
  emit delta
```

### `transition`

Representa mudança explícita entre estados tipados:

```text
transition Validate
  from RawObservation
  to ValidObservation
  restrict quality != "rejected"
  emit quality
```

## 6. Instruções

- `let`: cria nome local;
- `judge`: exige que uma condição seja verdadeira;
- `restrict`: declara uma restrição;
- `stabilize`: marca alvo como estabilizado;
- `emit`: manifesta o resultado;
- `project`: projeta expressão em tipo ou nomes;
- `bind`: cria relação explícita entre duas expressões;
- `if/else`: ramificação.

`condense` e `transition` precisam possuir ao menos um `emit` em seu corpo
sintático e precisam emitir em todos os caminhos estruturais possíveis.

Emissões de uma mesma operação precisam possuir tipos compatíveis.

## 7. Expressões

T 1.0 aceita um subconjunto determinístico de expressões compatíveis com
expressões Python:

- nomes;
- literais;
- listas;
- chamadas;
- acesso qualificado;
- operações aritméticas `+`, `-`, `*`, `/`, `//`, `%` e `**`;
- comparações `==`, `!=`, `<`, `<=`, `>` e `>=`;
- `and`, `or`, `not`;
- `true`, `false` e `null`, traduzidos semanticamente.

Expressões multilinha ainda não pertencem ao núcleo implementado.

## 8. Diagnósticos

Faixas:

| Faixa | Fase |
|---|---|
| `T1xxx` | léxico e indentação |
| `T2xxx` | sintaxe e estrutura |
| `T3xxx` | semântica |

Todo diagnóstico contém:

- código;
- severidade;
- mensagem;
- arquivo;
- linha;
- coluna;
- fim da região;
- dica opcional.

Diagnósticos semânticos congelados nesta implementação:

| Código | Significado |
|---|---|
| `T3001` | declaração duplicada |
| `T3002` | tipo de entrada desconhecido |
| `T3003` | tipo de transição desconhecido |
| `T3010` | trace duplicado |
| `T3011` | tipo de trace desconhecido |
| `T3020` | operação não emite em todos os caminhos |
| `T3021` | expressão inválida |
| `T3030` | nome não resolvido |
| `T3031` | nome redefinido no escopo |
| `T3032` | condição não booleana |
| `T3033` | tipos incompatíveis |
| `T3034` | tipos de emissão incompatíveis |
| `T3035` | função desconhecida |
| `T3036` | quantidade inválida de argumentos |
| `T3037` | acesso qualificado ainda não resolvido |
| `T3038` | expressão fora do subconjunto executável |
| `T3039` | tipo de projeção desconhecido |

## 9. Semântica executável de referência

O backend `python-reference/0.2` materializa cada `condense` e `transition`
como uma operação pura sobre um objeto de entrada:

- `judge`: bloqueia a execução quando a condição é falsa;
- `restrict`: bloqueia a execução quando a restrição não é satisfeita;
- `project`: registra valor, tipo ou nomes projetados como evidência;
- `bind`: registra os dois lados da relação como evidência;
- `stabilize`: registra o valor e muda o estado da execução para `stable`;
- `emit`: encerra o caminho atual e manifesta o resultado;
- `if/else`: executa exatamente um ramo.

O envelope de emissão contém:

```text
artifact_id
module
operation
state
input
result
evidence
```

`input` é uma cópia integral da entrada recebida. Campos opcionais ausentes
podem assumir `null` no ambiente interno, mas não são acrescentados à cópia
preservada.

Uma lista de entradas pode ser executada em lote. O backend precisa preservar
a ordem e produzir um envelope por entrada. Como T 1.0 não possui relógio,
aleatoriedade, I/O em expressões ou funções externas, suas operações são
determinísticas e podem ser memoizadas por operação.

O grafo `metamorfose-graph/0.1` deriva da IR e explicita definições, usos,
dependências de controle, efeitos e custo estrutural. Ele não altera o
significado do programa.

## 10. Estados semânticos reservados

- `unknown`
- `partial`
- `stable`
- `blocked`

Os nomes permanecem reservados para a CrisálidaIR e o runtime.

## 11. Compatibilidade

Um programa válido em T 1.0 não pode mudar de significado em uma atualização
1.x sem:

- feature explícita;
- diagnóstico de migração;
- nova versão da especificação.

## 12. Programa canônico

```text
module casulo.flood_rs

field HydroCell
  trace precipitation: Number
  trace evapotranspiration: Number
  trace surface_flow: Number
  trace base_flow: Number

condense WaterBalance in HydroCell
  judge precipitation >= 0
  let storage_change = precipitation - evapotranspiration - surface_flow - base_flow
  stabilize storage_change
  emit storage_change
```
