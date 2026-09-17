# ARQUITETURA DO MOTOR GENERATIVO E DA VM

## 1. Princípio

O CasuloEngine é o motor do produto; o modelo neural é um componente de inferência substituível. A inteligência emerge da composição:

```text
I_Casulo = GenerativeModel
         + LivingMemory
         + CollaborationContract
         + IntentPlanner
         + TForge
         + Tools
         + Simulation
         + Verification
         + Materializer
```

O release owner não deve ser um wrapper de linha de comando nem um prompt gigante sobre um modelo.

## 2. Componentes novos

### `OwnerGenerativeEngineAdapter`

Implementa `CasuloEngine` usando inferência local e streaming. Substitui a referência determinística no caminho owner, sem removê-la dos testes.

### `LocalModelRuntime`

- carrega pesos verificados;
- aplica limites de RAM/contexto;
- oferece streaming e cancelamento;
- registra model card, licença, hash e quantização;
- expõe sampling configurável por política;
- não recebe secrets ou capabilities diretamente.

### `ContextAssembler`

Constrói contexto ativo a partir de:

- fala atual;
- thread da criação;
- decisões confirmadas/rejeitadas;
- CollaborationContract;
- schemas T necessários;
- resultados de ferramentas;
- constraints obrigatórias.

Não injeta toda a memória. Nenhuma sumarização pode eliminar restrição confirmada.

### `GenerativeDialogueCore`

Produz fala streaming alinhada ao contrato Science Bros. Mantém Presence separado dos jobs pesados e aceita barge-in.

### `IntentPlanner`

Converte conversa em hipóteses e `IntentDelta.PROPOSED`. O modelo não confirma sua própria interpretação.

### `TProgramSynthesizer`

Gera ou modifica `CreationSpec`, código T, tests e manifests por regiões. Nunca grava diretamente a versão viva.

### `VerifierRepairLoop`

```text
candidate
  -> schema validation
  -> capability check
  -> T compile
  -> impacted tests
  -> simulation
  -> diagnostics
  -> bounded generative repair
  -> candidate or explicit failure
```

Reparo possui número máximo de tentativas, orçamento e histórico. Não esconde erro final.

### `StochasticTrace`

Para cada operação generativa registra sem expor isso na conversa normal:

```text
operation_id
model_id + model_hash
sampling_policy_id
seed_if_available
context_digest
tool_receipts
candidate_hashes
chosen_candidate
repair_attempts
final_state
```

Isso dá auditabilidade sem exigir que duas execuções produzam a mesma resposta.

### `OwnerInspectionRecorder`

Registra, sob comando explícito:

- nota falada ou textual;
- timestamp e estado visual;
- creation/version ativa;
- trecho de conversa selecionado;
- categoria: conversa, inteligência, voz, latência, visual, erro ou desejo;
- snapshot associado.

## 3. Fluxo generativo

```text
Voice partials
  -> semantic endpointing
  -> final utterance
  -> ContextAssembler
  -> GenerativeDialogueCore + IntentPlanner
  -> IntentDelta.PROPOSED
  -> human confirmation when material
  -> TProgramSynthesizer
  -> VerifierRepairLoop
  -> CreationSpec candidate
  -> live preview
  -> correction / agreement
  -> Materializer
```

Dialogue e geração de artefato podem ocorrer em paralelo, mas somente dados confirmados entram na criação viva.

## 4. Sampling

O caminho owner normal precisa ter variância real:

- sampling não degenerado;
- política diferente para diálogo, planejamento e código;
- código favorece precisão e reparo;
- diálogo favorece naturalidade;
- brainstorm favorece diversidade;
- seed fixa somente em debug;
- segurança nunca depende de amostragem.

Não congelar valores universais de temperatura/top-p antes de observar o modelo real. Calibrar por testes de produto e registrar a política, sem transformar o trabalho em benchmark científico.

## 5. Arquitetura da VM

```text
Windows host
  -> CasuloVMController
  -> QEMU + WHPX
  -> Q35 + OVMF
  -> Casulo Native guest
       -> virtio transport
       -> system volume read-only
       -> owner data overlay
       -> display/input/audio bridge
       -> Casulo Shell
       -> OwnerGenerativeEngineAdapter
```

QEMU/WHPX é infraestrutura, não a identidade do produto. O produto próprio inclui a imagem guest, o controller, os drivers, o formato de estado, a experiência, o motor e o lifecycle.

Referências oficiais:

- QEMU WHPX: https://www.qemu.org/docs/master/system/whpx.html
- VirtIO: https://www.qemu.org/docs/master/system/devices/virtio/index.html
- VirtIO GPU: https://www.qemu.org/docs/master/system/devices/virtio/virtio-gpu.html
- QEMU System: https://www.qemu.org/docs/master/system/

## 6. `CasuloVMController`

Comandos alvo equivalentes:

```text
casulo vm doctor
casulo vm create
casulo vm start
casulo vm stop
casulo vm snapshot <name>
casulo vm restore <name>
casulo vm export-feedback
casulo vm reset-overlay
```

Regras:

- caminhos explícitos e confinados;
- imagem base imutável;
- overlay copy-on-write;
- nunca usar disco físico como target;
- shutdown gracioso antes de forçar parada;
- QMP restrito a transporte local autenticado;
- argumentos construídos como array, nunca shell concatenado;
- versão QEMU/OVMF registrada;
- crash não corrompe a base.

## 7. Dispositivos virtuais mínimos

- UEFI framebuffer como bootstrap;
- virtio/PCI transport;
- block para volume do sistema e owner data;
- input suficiente para fallback e acessibilidade;
- rede negada por default, habilitada apenas para uso explicitamente necessário;
- áudio de entrada/saída e cancelamento;
- relógio monotônico;
- entropy;
- clipboard e shared folder ausentes por default.

Para a primeira versão, renderer 2D é suficiente. Aceleração 3D não pode bloquear o motor generativo.

## 8. Áudio dentro da VM

Ordem de preferência:

1. driver virtio-sound estável no guest;
2. `VmAudioBridge` first-party, local e capability-scoped;
3. fallback textual explícito.

O bridge não pode virar túnel genérico host/guest. Ele transporta PCM/eventos de sessão limitados, suporta cancelamento e não persiste áudio por default.

## 9. Presença e renderer

O renderer consome `VisualSemanticModel`, nunca texto cru do modelo.

Estados visuais mínimos:

- listening;
- thinking;
- proposing;
- generating;
- compiling;
- repairing;
- simulating;
- awaiting confirmation;
- ready;
- failed honestly.

A estética Stark + Jobs usa os tokens anteriores, mas todos os valores permanecem substituíveis. Nenhum trabalho de polimento pode atrasar o primeiro diálogo generativo funcional.

## 10. Estrutura de código alvo

Adaptar à árvore real sem reescrita total:

```text
intelligence/
  contracts/
  owner-engine/
  local-model-runtime/
  context-assembler/
  dialogue/
  planning/
  synthesis/
  repair/
  model-registry/
platform/
  native/
    virtio/
    vm-audio/
  hosted/
vm/
  controller/
  qemu-profile/
  images/
  snapshots/
  feedback/
experience/
  creation-field/
  provisional-stark-jobs-theme/
tests/
  generative-contract/
  vm-e2e/
  ux-contract/
```

## 11. Fronteiras

- `casulo-public` não liga o motor owner;
- Cloud continua `RELEASE_LOCKED`;
- modelo não lê secret store;
- modelo propõe, policy decide;
- texto importado é dado não confiável;
- ferramentas têm schemas e capabilities;
- VM não monta disco interno;
- base VM não contém chaves privadas;
- feedback só é gravado após comando do usuário.

