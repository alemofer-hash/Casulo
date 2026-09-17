# ARQUITETURA COMPLETA DO CASULO

## 1. Princípio arquitetural

A interface conversacional, a memória, a geração e a execução precisam ser desacopladas. O Guia nunca pode ficar mudo porque um compilador, modelo ou renderizador está ocupado.

```text
Inventor
  <-> Voice Duplex
  <-> Guide Presence
  <-> Intent Engine
  <-> Living Memory
  <-> Creation Model
  <-> T Forge / Compiler
  <-> Simulation Runtime
  <-> Materializer

Em paralelo:
  Resource Planner
  Security Broker
  Renderer
  Background Workers
```

## 2. Perfis de execução

### 2.1 Hosted Product Profile

Executa inicialmente em Windows/Linux/macOS sobre APIs maduras de áudio, GPU, filesystem e rede. Serve para desenvolver e validar toda a experiência sem esperar drivers do kernel próprio.

### 2.2 Casulo Native Profile

Sistema x86-64/UEFI próprio. Implementa progressivamente HAL, memória, processos, IPC, áudio, armazenamento, GPU e isolamento. O código de domínio não pode conhecer se está no perfil hosted ou native.

### 2.3 Exported Agent Profile

Runtime mínimo embutido no artefato materializado. Pode ser nativo, contêiner, WASI, serviço ou pacote de linguagem.

Essa separação não reduz o Casulo a um aplicativo. Ela impede que a ausência inicial de drivers bloqueie a criação da experiência e força uma ABI portável.

## 3. Camadas

### L0 — Boot e Kernel

- x86-64 UEFI;
- boot reproduzível em QEMU/OVMF;
- console serial e framebuffer;
- memória física/virtual;
- interrupções e timer;
- SMP;
- ring 3 e isolamento;
- syscalls versionadas;
- IPC;
- watchdog;
- panic dump;
- shutdown/reboot seguro.

O release inicial não grava discos reais automaticamente.

### L1 — HAL e serviços fundamentais

Interfaces versionadas:

- `DisplayDevice`;
- `AudioCapture` / `AudioPlayback`;
- `Clock`;
- `Entropy`;
- `Storage`;
- `Network`;
- `Accelerator`;
- `SecureSecretStore`;
- `ProcessSandbox`.

Cada interface tem implementação hosted e, quando disponível, native.

### L2 — Runtime T

- loader `.tcap`;
- verificação de hash, assinatura e ABI;
- capability broker;
- executor de grafos;
- scheduler semântico;
- cancelamento cooperativo;
- snapshots e reidratação;
- rastreio explicável;
- quarentena de artefatos inválidos.

Filas revisadas para produto:

- `PRESENCE`: voz, interrupção e resposta do Guia;
- `FLOW`: caminho necessário à criação atual;
- `SYSTEM`: serviços fundamentais;
- `BACKGROUND`: geração, compilação, indexação e simulação não bloqueantes;
- `AUDIT`: proveniência e consolidação;
- `RETRY`: repetição limitada;
- `LOW_CONFIDENCE`: hipóteses que não podem consolidar estado;
- `QUARANTINE`: violação, corrupção ou permissão ausente.

### L3 — Modelo vivo de domínio

Objetos canônicos:

- `InventorProfile`;
- `CollaborationContract`;
- `ConversationSession`;
- `IntentDelta`;
- `CreationSpec`;
- `BehaviorContract`;
- `MemoryPolicy`;
- `CapabilityGrant`;
- `SimulationScenario`;
- `MaterializationPlan`;
- `ArtifactVersion`.

JSON canônico serve para inspeção. O formato persistente real deve ser versionado, validado e migrável.

### L4 — Memória viva

Armazenamento append-only de eventos + projeções derivadas.

```text
RawEventLog
  -> EpisodicIndex
  -> SemanticGraph
  -> CreationProjection
  -> CollaborationProjection
  -> RetrievalContext
```

O dado bruto nunca é substituído por resumo. Memórias derivadas apontam para suas origens. Criptografia local, exclusão verificável e exportação do usuário são obrigatórias.

### L5 — Voice Duplex

Pipeline local:

```text
microfone
  -> VAD
  -> streaming ASR
  -> partial transcript
  -> semantic endpointing
  -> IntentDelta

Guide response
  -> semantic chunking
  -> streaming TTS
  -> audio playback
  <- barge-in/cancelamento imediato
```

Requisitos:

- fala e processamento simultâneos;
- interrupção pelo usuário em qualquer instante;
- transcrição parcial marcada como provisória;
- proteção contra consolidar pensamento incompleto;
- fallback de texto/acessibilidade;
- nenhum áudio enviado externamente por padrão.

### L6 — Guia

O Guia é uma composição, não um único prompt:

- `GuideDialogue`: conversa presente;
- `GuideRelationship`: contrato de colaboração;
- `GuideContext`: recuperação de memória;
- `GuideUncertainty`: decide se precisa esclarecer;
- `GuideCompanion`: mantém conversa durante espera;
- `GuideProgress`: traduz marcos reais em linguagem humana.

O Guia não grava diretamente o estado confirmado. Ele propõe `IntentDelta`; validadores e, quando necessário, o Inventor confirmam.

### L7 — Intelligence Runtime local

Bootstrap sem API:

- adapter para modelo de pesos abertos executado localmente;
- embeddings locais;
- ASR local;
- TTS local;
- roteamento entre modelos pequenos especializados;
- possibilidade futura de pesos próprios Casulo.

O runtime local deve ser substituível por interface. O Casulo não mistura identidade do produto com um modelo específico.

### L8 — T Forge

Transforma o modelo de criação em programa T incremental:

```text
IntentDelta
  -> constraint merge
  -> CreationSpec revision
  -> affected subgraph detection
  -> T patch
  -> semantic analysis
  -> IR delta
  -> graph delta
  -> impacted tests
  -> preview
```

Mudanças localizadas não podem regenerar regiões não afetadas sem justificativa registrada.

### L9 — Simulation Runtime

- cenários sintéticos;
- relógio virtual;
- serviços falsos determinísticos;
- aprovação humana simulada;
- falhas e timeouts injetáveis;
- comparação de versões;
- pausa por voz;
- replay exato quando determinístico.

Nenhuma simulação usa credencial ou ação real.

### L10 — Creation Field Renderer

Renderer orientado a estado, não a decoração. Ele recebe um `VisualSemanticModel`, nunca o texto bruto do LLM.

```text
uncertain -> mist
proposed -> translucent
confirmed -> amber solid
computing -> cobalt pulse
blocked -> contained stillness
correcting -> local dissolve/reform
materialized -> compact artifact
```

Renderização tem prioridade inferior à voz, memória e segurança.

### L11 — Materializer

Pipeline:

```text
CreationSpec + T program + policies + tests
  -> target resolver
  -> dependency closure
  -> secret exclusion
  -> build
  -> sandbox test
  -> manifest + SBOM + hashes
  -> export
```

Targets iniciais, por ordem:

1. pacote Casulo editável;
2. processo local;
3. API HTTP local;
4. contêiner OCI;
5. servidor MCP;
6. executável standalone quando dependências permitirem;
7. SDKs.

### L12 — Installer e Machine Profile

Instalação calibra, sem benchmark científico:

- compatibilidade CPU/GPU;
- RAM/VRAM;
- throughput aproximado de inferência;
- latência de áudio;
- capacidade de renderização;
- armazenamento;
- estabilidade térmica apenas como proteção.

Produz estimativas humanas de duração. Não produz alegações públicas de superioridade.

## 4. Fluxo end-to-end

```text
1. Boot
2. Guia fica disponível
3. Inventor fala
4. ASR emite hipóteses parciais
5. Endpointing fecha unidade de pensamento
6. Intent Engine produz IntentDelta
7. Memory grava evento bruto e proveniência
8. Constraint Engine tenta aplicar delta
9. Ambiguidade material -> Guia pergunta
10. Delta aceito -> CreationSpec nova versão
11. T Forge recompila subgrafo afetado
12. Renderer atualiza forma
13. Background simula e valida
14. Guia continua conversando
15. Inventor interrompe/corrige
16. Acordo -> Materializer exporta
```

## 5. Fronteiras de confiança

- microfone e memória pessoal: dados de alta sensibilidade;
- modelos locais: não recebem acesso direto a secrets;
- ferramentas: capability tokens mínimos e revogáveis;
- materialização: ambiente isolado;
- exportação: secrets nunca embutidos;
- rede: negada por padrão no Casulo Native e por criação;
- updates: assinados e reversíveis;
- telemetria: local por padrão, opt-in externo.

## 6. Estrutura de monorepo alvo

Adapte sem reescrever o que já funciona:

```text
Casulo/
  AGENTS.md
  README.md
  docs/
    product/
    architecture/
    spec/
    decisions/
    archive/research/
  compiler/
    python-reference/
    t-frontend/
    t-ir/
    t-codegen/
  runtime/
    t-runtime/
    scheduler/
    tcap/
  core/
    domain/
    memory/
    intent/
    security/
  guide/
    dialogue/
    relationship/
    progress/
  intelligence/
    inference/
    embeddings/
    asr/
    tts/
    model-registry/
  experience/
    shell/
    creation-field/
    design-system/
  platform/
    hosted/
    native/
  materializer/
    targets/
    sandbox/
  installer/
  tests/
    unit/
    integration/
    e2e/
    security/
    ux-contract/
  release/
```

## 7. Decisão de implementação

Rust é o default para kernel, runtime, serviços de longa duração, segurança, áudio e renderer. Python permanece como implementação de referência e ferramenta de migração do compilador T até que a paridade esteja demonstrada. C/C++ pode existir atrás de FFI estrita para runtimes locais de inferência. T descreve agentes, políticas, memória, efeitos e fluxo; não substitui assembly, drivers ou kernels numéricos automaticamente.

