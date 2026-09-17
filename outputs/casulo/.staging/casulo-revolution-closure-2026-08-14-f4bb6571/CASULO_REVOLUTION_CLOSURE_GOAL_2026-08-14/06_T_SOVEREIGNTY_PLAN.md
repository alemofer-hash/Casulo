# LINGUAGEM T — PLANO DE SOBERANIA

## 1. O que “feito com T” significa

Soberania não é contar linhas. T é soberana quando as decisões que definem a
criação — intenção, composição, estado, efeitos, políticas, testes e pacote —
são expressas, verificadas e executadas por contratos T.

Python, Rust, C e C++ podem continuar como bootstrap, compilador, driver,
kernel, runtime numérico ou binding. Eles não podem esconder lógica de produto
que T afirma governar.

## 2. Superfícies e métrica

Auditar estas superfícies:

| Superfície | Peso inicial | Condição `T_DRIVEN` |
|---|---:|---|
| intenção/requisitos | 3 | schema e transições em T |
| lógica do agente | 3 | entrypoint e estados em T |
| tools/composição | 3 | bindings e workflows T |
| memória | 3 | operações/policies T |
| jobs/concorrência | 3 | lifecycle/cancelamento T |
| effects/capabilities | 4 | decisão crítica integral em T |
| interfaces | 2 | view model/event contract T |
| testes/simulação | 3 | specs/properties invocáveis por T |
| empacotamento | 3 | manifest/target graph T |

Para superfície `j`, use `d_j ∈ {0, 0.5, 1}`:

```text
S_T = sum(w_j * d_j) / sum(w_j)
```

Gate alvo deste Goal:

```text
S_T >= 0.80
AND effects/capabilities == 1
AND intent/requirements == 1
AND materialization decisions == 1
```

O peso final é congelado no RC1 antes de migrar código. Não alterar pesos depois
para fabricar aprovação.

## 3. Gaps a auditar/implementar

### Módulos e pacotes

- namespaces/imports públicos e privados;
- semantic versioning e lockfile;
- content-addressed compilation;
- package manifest, license e SBOM;
- visibilidade e módulos selados.

### Tipos

- records/enums/result/option estáveis;
- refinements para unidades, ranges e non-empty;
- generics mínimos sem explosão de compilador;
- tipos de resources/handles não copiáveis;
- tipos versionados de schema e migração.

### Effects e capabilities

- effect rows ou conjunto explícito equivalente;
- capability tokens não forjáveis;
- escopo, expiração e revogação;
- separação `simulate`/`execute`;
- `secret.ref` sem acesso ao valor;
- `network`, `filesystem`, `process`, `audio`, `device` deny-by-default.

### Concorrência estruturada

- tasks com parent/child;
- cancel token e deadlines monotônicos;
- channels tipados e bounded;
- select/backpressure;
- rejection de stale result;
- cleanup determinístico.

### Memória e persistência

- transactions;
- event append + projections;
- snapshots/migrations;
- content hashes;
- sensitivity/retention types;
- APIs de export/delete.

### Interfaces

- `VisualSemanticModel` tipado;
- event-driven view state;
- accessibility semantics;
- bindings de voz;
- nenhuma UI baseada em string neural crua.

### Teste e simulação

- `test`, `property`, `fixture` e `double` first-party;
- deterministic clock/random/IO em simulation;
- fault injection;
- coverage por RequirementGraph;
- receipts e replay.

### Materialização

- target declarations;
- dependency/runtime closure;
- manifest/SBOM/hashes;
- secret exclusion;
- import/round-trip;
- compatibility and migration.

## 4. Semantic IR necessário

Estender a IR existente, adaptando nomes à árvore real:

```text
ProjectDecl
RequirementDecl
EvidenceDecl
GuidePolicyDecl
UniverseDecl
TransitionDecl
JobDecl
CapabilityRequest
MaterializationTarget
ForeignBoundaryDecl
```

Lowering produz grafo auditável. Mudança local invalida apenas dependentes
downstream; source alterado nunca pode se esconder atrás de affected paths
incorretos.

## 5. `ForeignBoundaryManifest`

Cada componente externo declara:

```text
boundary_id
implementation_language
artifact_hash
license
ABI/API_version
input/output types
memory ownership
threading model
effects
capabilities
limits/timeouts
failure mapping
sandbox profile
```

Regras:

- ABI estreita e fuzzável;
- sem `shell=True` ou comando concatenado;
- nenhum callback arbitrário no simulation path;
- erros estrangeiros viram diagnostics tipados;
- upgrade exige compatibility test e SBOM novo;
- ausência/hash mismatch falha explicitamente.

## 6. Migração por estrangulamento, não reescrita

1. inventariar comportamento atual por superfície;
2. escrever contract T antes da migração;
3. manter adapter para implementação existente;
4. mover decisão/policy para T;
5. provar equivalência e failure semantics;
6. remover duplicação somente após gate;
7. preservar fallback de rollback por uma versão.

Prioridade:

```text
capabilities/effects
-> RequirementGraph/workflows
-> jobs/cancelamento
-> memória
-> tools
-> materialization
-> interfaces
```

## 7. Gates T

- typecheck de packages owner;
- negative tests para forja de capability;
- cancelamento e stale results;
- ABI C/C++/Rust contra stubs pinados;
- source/IR/TCAP hashes e reproducible build;
- alteração localizada preserva hashes não afetados;
- pacote exportado executa sem Python do repositório quando o target promete
  standalone;
- `T_SOVEREIGNTY_MATRIX.json` audita cada superfície e evidência;
- `S_T >= 0.80` sem exceções críticas.

## 8. Claims honestos

Autorizado:

> “T governa a intenção, composição, efeitos e materialização do Casulo; runtimes
> e kernels externos entram por fronteiras tipadas e auditadas.”

Não autorizado:

> “Todo byte do Casulo foi escrito em T” ou “T substitui pesos, LLVM, drivers e
> kernels numéricos.”

