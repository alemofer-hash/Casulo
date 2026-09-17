# MATRIZ DE LACUNAS DA LINGUAGEM T

## 1. Baseline histórico auditado

T 1.0 possuía:

- `field/trace`;
- `condense`;
- `transition`;
- `let`, `project`, `bind`, `restrict`, `judge`, `stabilize`, `emit`, `if`;
- tipos `Text`, `Number`, `Bool`, `Time`, `Date`, `Duration`, `Any`, opcionais e listas;
- frontend com lexer/parser/AST/análise;
- CrisálidaIR 0.1;
- Metamorfose Graph 0.1;
- backend Python de referência;
- backend C99/nativo;
- tensores e autodiferenciação experimentais;
- workspace local e lockfile;
- artefatos canônicos por hash.

## 2. Lacunas conhecidas no snapshot

| ID | Estado | Lacuna | Necessidade de produto | Gate |
|---|---|---|---|---|
| T-GAP-001 | KNOWN_HISTORICAL_GAP | `use` ordena módulos, mas não liga símbolos entre eles | biblioteca real e stdlib | símbolos cross-module + testes ABI |
| T-GAP-002 | KNOWN_HISTORICAL_GAP | IR sem blocos básicos/SSA/phi | deltas, otimização e controle robusto | IR vNext com CFG verificável |
| T-GAP-003 | KNOWN_HISTORICAL_GAP | efeitos são rótulos derivados, não sistema de tipos | impedir ação não autorizada | effect/capability checking estático |
| T-GAP-004 | KNOWN_HISTORICAL_GAP | custo apenas estrutural | estimativa de tempo e scheduling | cost model calibrável, nunca alegação universal |
| T-GAP-005 | KNOWN_HISTORICAL_GAP | cache por operação inteira | correção localizada | hashing e invalidação por subgrafo |
| T-GAP-006 | KNOWN_HISTORICAL_GAP | rota `learn` possui parser/gerador especializado | uma única linguagem e IR | integrar ou arquivar a rota legada |
| T-GAP-007 | KNOWN_HISTORICAL_GAP | tensores concentrados em rank-2/matmul | inferência e voz | shape system, broadcast e operadores necessários |
| T-GAP-008 | KNOWN_HISTORICAL_GAP | sem GPU/accelerator portable | render e modelos locais | HAL + backends explicitamente opcionais |
| T-GAP-009 | KNOWN_HISTORICAL_GAP | expressões baseadas em subconjunto Python textual | segurança e compilação própria | expression AST nativa, sem `ast.parse` como semântica final |
| T-GAP-010 | KNOWN_HISTORICAL_GAP | sem ligação de bibliotecas/FFI formal | ASR/TTS/inferência/export | ABI/FFI versionada e capability-safe |

## 3. Novas capacidades obrigatórias

| ID | Estado | Capacidade | Forma mínima |
|---|---|---|---|
| T-NEW-001 | NEW_PRODUCT_REQUIREMENT | registros, enums e unions | `record`, `enum`, `Result<T,E>` |
| T-NEW-002 | NEW_PRODUCT_REQUIREMENT | funções e interfaces | assinatura tipada, generics limitados |
| T-NEW-003 | NEW_PRODUCT_REQUIREMENT | async/streams/cancelamento | voz, eventos e background workers |
| T-NEW-004 | NEW_PRODUCT_REQUIREMENT | erros, timeout e retry | políticas explícitas e limitadas |
| T-NEW-005 | NEW_PRODUCT_REQUIREMENT | capacidades/permissões | acesso mínimo, revogável, auditável |
| T-NEW-006 | NEW_PRODUCT_REQUIREMENT | memória persistente | schema, retenção, proveniência, delete/export |
| T-NEW-007 | NEW_PRODUCT_REQUIREMENT | eventos e gatilhos | tempo, voz, arquivo, webhook, sistema |
| T-NEW-008 | NEW_PRODUCT_REQUIREMENT | agentes | identidade, comportamento, ferramentas, limites |
| T-NEW-009 | NEW_PRODUCT_REQUIREMENT | aprovação humana | gates antes de efeitos sensíveis |
| T-NEW-010 | NEW_PRODUCT_REQUIREMENT | modelos locais | inferência/embedding/ASR/TTS como capabilities |
| T-NEW-011 | NEW_PRODUCT_REQUIREMENT | patches incrementais | delta tipado e escopo afetado |
| T-NEW-012 | NEW_PRODUCT_REQUIREMENT | contratos de colaboração | ritmo, correção, pressão e comunicação |
| T-NEW-013 | NEW_PRODUCT_REQUIREMENT | simulação | relógio virtual e adapters falsos |
| T-NEW-014 | NEW_PRODUCT_REQUIREMENT | materialização | target, dependências, secrets e testes |
| T-NEW-015 | NEW_PRODUCT_REQUIREMENT | migrações | schemas e artefatos versionados |

## 4. Proposta de superfície T vNext

Esta sintaxe é uma direção para RFC e testes, não deve ser implementada literalmente antes da auditoria.

```t
module personal.project_continuity

capability Calendar.read
capability Notification.write requires approval when urgent == false

record Project
  trace id: Text
  trace name: Text
  trace last_activity: Time
  trace status: ProjectStatus

memory ProjectMemory
  stores [Project]
  retention until user_deletes
  provenance required

agent ContinuityGuardian
  listens Voice.Intent
  remembers ProjectMemory
  may Calendar.read
  may Notification.write

  policy NeverAbandonAlone
    restrict archive_project without HumanApproval

  on inactivity(project)
    let context = infer_pause_context(project)
    judge confidence(context) >= 0.70 else ask_user
    propose next_step(context)
    emit proposal
```

## 5. Semântica mínima obrigatória

### 5.1 Tipos

- sem `Any` atravessando fronteira de capability sem validação;
- unions exaustivas;
- optional explícito;
- unidades e tempo com tipos distintos;
- schemas serializáveis e versionados;
- refinements para limites críticos.

### 5.2 Efeitos

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

Todo efeito deve possuir capability. Efeitos não declarados são erro de compilação ou quarentena no runtime.

### 5.3 Concorrência

- structured concurrency;
- task possui pai, budget e cancellation token;
- nenhuma task órfã;
- `PRESENCE` pode interromper `BACKGROUND`;
- writes de memória confirmada são serializados por criação;
- simulações são isoladas do mundo real.

### 5.4 Deltas

Cada `IntentDelta` inclui:

```text
delta_id
creation_id
base_version
operations[]
rationale
source_event_ids[]
confidence
confirmation_state
affected_paths[]
```

Aplicação exige base compatível, invariantes satisfeitas e ausência de permissão implícita.

### 5.5 `.tcap vNext`

Preservar princípios do v1 e acrescentar:

- schema de agente;
- schemas de memória;
- grafo de capabilities;
- políticas de aprovação;
- targets de materialização;
- model cards e hashes dos pesos;
- SBOM;
- testes embutidos;
- migrações;
- política de rede;
- política de secrets;
- interface de observabilidade;
- assinatura opcional e cadeia de confiança.

## 6. Ordem de fechamento

1. auditar estado real;
2. congelar T 1.0 e golden tests;
3. RFC de efeitos/capabilities;
4. expression AST própria;
5. módulos e ABI;
6. IR com CFG/SSA suficiente;
7. records/enums/result;
8. async/streams/cancelamento;
9. memória e eventos;
10. agentes e aprovação humana;
11. delta compilation;
12. materialização.

Não adicionar sintaxe antes de escrever semântica, diagnósticos, lowering, golden tests e migração.

## 7. Auditoria obrigatória no repo atual

O Codex deve gerar `docs/product/T_GAP_AUDIT.md` com, para cada ID:

- evidência no código;
- arquivo/símbolo;
- estado atual;
- teste existente;
- decisão: implementar, adaptar, adiar ou marcar não aplicável;
- dependências entre lacunas.

