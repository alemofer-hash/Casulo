# ARQUITETURA-ALVO INTEGRADA

## 1. Princípio

O modelo neural é uma fonte estocástica de hipóteses. O Casulo é o sistema que
mantém identidade, memória, intenção, prova, ferramentas, segurança e forma.

```text
CasuloIntelligence = BootstrapModel
                   + CasuloAdaptersAndSpecialists
                   + GuideContinuityKernel
                   + LivingMemory
                   + IntentAndRequirementGraph
                   + SemanticMultiverse
                   + T Runtime / T Forge
                   + VerificationMesh
                   + CapabilityBroker
                   + Materializer
```

Criatividade é probabilística. Autoridade, efeitos, promoção e publicação são
determinísticos e transacionais.

## 2. Visão em camadas

```text
┌──────────────────────────────────────────────────────────────┐
│ EXPERIENCE PLANE                                            │
│ Creation Field · Voice Duplex · Guide Presence · Launcher   │
├──────────────────────────────────────────────────────────────┤
│ COLLABORATION PLANE                                         │
│ GuideContinuityKernel · DialogueDirector · ConstraintLedger │
│ ContradictionEngine · PersonalCollaborationPolicy           │
├──────────────────────────────────────────────────────────────┤
│ CREATION PLANE                                              │
│ IntentGraph · RequirementGraph · EpistemicGate · Planner    │
│ DomainPackRegistry · SemanticFulfillmentGate · RepairLoop   │
├──────────────────────────────────────────────────────────────┤
│ SEMANTIC PLANE                                              │
│ Catalog · Router · UniverseLifecycle · Transitions          │
│ SufficientStateCompiler · MemoryThermostat · Delta Store    │
├──────────────────────────────────────────────────────────────┤
│ T SOVEREIGN PLANE                                           │
│ T Frontend · Types · Effects · Capabilities · IR · TCAP     │
│ Scheduler · FFI Contracts · Forge · Simulation              │
├──────────────────────────────────────────────────────────────┤
│ MODEL PLANE                                                 │
│ Model Registry · Qwen Bootstrap · Casulo Adapters           │
│ Specialist Pool · Training Factory · llama.cpp Runtime      │
├──────────────────────────────────────────────────────────────┤
│ TRUST / MATERIALIZATION PLANE                               │
│ Capability Broker · Sandbox · Secrets · Provenance          │
│ Export Targets · Import/Migrate · Update/Recovery           │
├──────────────────────────────────────────────────────────────┤
│ APPLIANCE PLANE                                             │
│ Casulo Native VM · Immutable Base · Overlay · HostAccel RPC │
│ Audio Bridge · One-click Controller · Signed Bundles        │
└──────────────────────────────────────────────────────────────┘
```

## 3. Eventos e autoridades

O backbone é um event log tipado. Cada evento contém:

```text
event_id, session_id, project_id, creation_id?, monotonic_time,
event_type, schema_version, producer, provenance_root,
payload_hash, previous_hash, sensitivity, retention_policy
```

Autoridades são separadas:

| Decisão | Pode propor | Pode autorizar |
|---|---|---|
| fala/hipótese | modelo/Guia | não aplicável |
| intenção material | modelo/Guide | humano |
| rota semântica | modelo/router | policy + contracts |
| ferramenta | planner | CapabilityBroker |
| efeito real | criação | humano + broker |
| memória durável | Guide | humano/política consentida |
| publicação | materializer | deterministic gates |
| update | updater | signature + policy |

Nenhum output neural carrega autoridade implícita.

## 4. Componentes centrais

### `GuideContinuityKernel`

Mantém thread, projetos, compromissos, hipóteses, rejeições, incertezas, estilo e
jobs ativos. É independente do processo de inferência e sobrevive ao restart.

### `ConstraintLedger`

Fonte autoritativa de restrições confirmadas. Entradas possuem escopo, origem,
versão, precedência, estado e prova. Restrições obrigatórias são sempre
reintroduzidas; nunca dependem de similaridade vetorial.

### `DialogueDirector`

Seleciona `EXPANSION`, `CRYSTALLIZATION`, `EXECUTION`, `REVIEW`, `WAITING` ou
`RECOVERY`. O modelo sugere; transições materiais são explicáveis e o usuário
pode mudar o modo naturalmente.

### `RequirementGraph`

Grafo de obrigações derivado da conversa. Cada nó declara tipo, dureza,
dependências, evidência esperada, verificador, estado e incerteza.

### `EpistemicGate`

Distingue conhecimento disponível, inferência, hipótese e lacuna. Impede o Guia
de inventar competência ou aceitar um verificador circular produzido pelo mesmo
candidato sem fonte independente.

### `SemanticFulfillmentGate`

Só aceita uma criação quando requisitos duros possuem evidência independente e
os requisitos suaves atingem o limiar definido pela própria criação.

### `ArchitectureRepairLoop`

Recebe gaps semânticos, diagnostics T, testes, simulação e feedback. Pode mudar
componentes e dependências dentro de orçamento; não apenas editar linhas.

### `T Sovereign Runtime`

Orquestra intents, workflows, transitions, jobs, effects e export. Bibliotecas
nativas entram somente por ABI/manifest versionados.

### `CasuloModelRegistry`

Registra base, quantização, adapter stack, especialistas, tokenizer, template,
licença, hashes, dataset lineage, compatibilidade e rollback.

### `HostAcceleratorService`

Enquanto o Native não executar todo o modelo, a aceleração do host usa protocolo
first-party estreito:

- transporte local/virtio/vsock ou canal explicitamente equivalente;
- handshake com nonce e versionamento;
- frames limitados e schemas fixos;
- sem shell, path arbitrário, clipboard ou filesystem genérico;
- cancelamento, deadline e backpressure;
- modelo/hash do serviço atestado ao guest;
- indisponibilidade vira modo degradado honesto.

Isso é uma fronteira de appliance, não uma alegação de Native completo.

## 5. Fluxo ponta a ponta

```text
audio capture
-> AEC/NS/AGC/VAD
-> streaming ASR + semantic endpoint
-> GuideContinuityKernel
-> DialogueDirector
-> memory/constraints/context assembly
-> neural dialogue stream (Presence)
-> IntentDelta.PROPOSED
-> RequirementGraph candidate
-> human confirmation when material
-> Semantic Multiverse route
-> T planning/synthesis/tests
-> compile + policy + fulfillment verification
-> bounded architecture repair
-> simulation in sandbox
-> live Creation Field from real receipts
-> agreement
-> multi-target materialization
-> clean-environment execution
-> round-trip import/re-edit
-> memory crystallization
```

## 6. Concorrência

Presence, inference, compilation, simulation and rendering are independent jobs.
Use structured concurrency:

- session owns child jobs;
- cancellation propagates downward;
- stale results carry generation/version and are rejected;
- no job mutates live state without compare-and-swap/transaction;
- UI progress derives only from event receipts;
- backpressure favors voice Presence over decorative rendering;
- user barge-in preempts TTS before model/job cancellation is evaluated.

## 7. Estado e persistência

```text
immutable:
  system image, model base, universe bases, released TCAPs

append-only:
  receipts, conversation events, provenance, training lineage

transactional projections:
  current CreationSpec, catalog, constraints, project views

volatile:
  KV cache, HOT universe tensors, partial ASR, unconfirmed hypotheses
```

Restart nunca ressuscita HOT como se ainda estivesse carregado. Ele reabre
projeções e reconstrói o working set com receipts novos.

## 8. Observabilidade sem vazar conteúdo

Métricas default:

- latências de presença/rota/wake/handoff/compile/repair;
- tamanhos e contagens;
- estados/cancelamentos/falhas;
- RSS/VRAM/bytes I/O quando disponíveis;
- hashes e IDs pseudônimos.

Prompts, áudio, transcripts, código e memória não entram em telemetria agregada
por padrão. Inspeção com conteúdo é local e opt-in.

