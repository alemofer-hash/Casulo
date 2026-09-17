# PLANO DE SPRINTS — PRIMEIRO CASULO GENERATIVO NA VM

Sprints são sequenciais por dependência. Nenhuma sprint pode ser aprovada por documentação ou scaffolding isolado.

## Sprint 0 — Preservar o Alpha e auditar o caminho real

### Entregas

- leitura integral de `AGENTS.md` e README;
- `git status` e inventário do worktree;
- checkpoint intencional do Alpha, sem `git add -A` cego;
- confirmação das regressões P0–P15 relevantes;
- mapa do engine determinístico atual;
- inventário de QEMU/OVMF/WHPX, modelos e espaço;
- estado durável novo;
- Cloud/public congelados.

### Gate

```text
ALPHA_PRESERVED_FOR_GENERATIVE_TRANSITION
```

## Sprint 1 — Runtime neural local e modelo autorizado

### Entregas

- `LocalModelRuntime` atrás de interface;
- shortlist baseada na máquina e licença;
- plano de download com consentimento quando necessário;
- model registry/card/hash;
- carga, geração streaming e cancelamento;
- limites de RAM/contexto;
- sampling estocástico real;
- processo/FFI sem shell textual;
- doctor read-only.

### Demo

O runtime produz duas continuações legitimamente diferentes da mesma entrada, em pt-BR, por geração neural local. Seed fixa reproduz bug em modo diagnóstico.

### Gate

```text
LOCAL_STOCHASTIC_INFERENCE_PASS
```

## Sprint 2 — OwnerGenerativeEngineAdapter

### Entregas

- adapter owner generativo no contrato `CasuloEngine`;
- `ContextAssembler` com constraints obrigatórias;
- streaming de `EngineEvent`;
- cancelamento e backpressure;
- `StochasticTrace`;
- reference engine removido do build owner e preservado em tests;
- nenhum endpoint externo.

### Demo

O Hosted Shell conversa com o engine local por várias voltas, lembra decisões e varia respostas sem perder constraints.

### Gate

```text
OWNER_GENERATIVE_ENGINE_PASS
```

## Sprint 3 — Química Science Bros

### Entregas

- contrato relacional versionado;
- `GenerativeDialogueCore` desacoplado de workers;
- expansão/cristalização naturais;
- discordância fundamentada;
- humor e calor calibráveis;
- política anti-bajulação/anti-corporativa;
- perguntas de alto valor;
- conversa durante jobs baseada em eventos reais;
- barge-in preservado;
- testes adversariais de tom.

### Demo

Em uma conversa nova, o Guia entende uma ideia incompleta, encontra uma consequência não dita, discorda de um ponto fraco e ajuda a transformar a ideia em direção de construção sem soar roteirizado.

### Gate

```text
SCIENCE_BROS_CONVERSATION_CONTRACT_PASS
```

Esse gate automatizado prova contratos e ausência de padrões rejeitados. A química subjetiva final pertence a Guilherme na inspeção.

## Sprint 4 — Conversa para programa T

### Entregas

- `IntentPlanner` generativo;
- `IntentDelta.PROPOSED` com proveniência;
- confirmação humana para mudanças materiais;
- `TProgramSynthesizer` incremental;
- geração de CreationSpec, T, tests e manifests;
- compile/analyze real;
- nenhum atalho legado;
- affected paths verificados pelo diff real.

### Demo

Uma ideia inédita produz programa T compilável. Uma correção conversacional altera apenas a região relevante.

### Gate

```text
GENERATIVE_T_SYNTHESIS_PASS
```

## Sprint 5 — Verificação, reparo e criação aberta

### Entregas

- `VerifierRepairLoop` limitado;
- diagnostics estruturados de volta ao engine;
- reparo de schema/compile/test;
- simulação sem efeitos reais;
- falha final explícita;
- suíte de tarefas inéditas em múltiplas categorias;
- detecção de templates/fixtures no caminho;
- materialização e round-trip.

### Demo

O engine recebe uma tarefa não presente nos exemplos, gera candidato inicialmente imperfeito, usa diagnóstico real para reparar, simula e materializa um agente funcional.

### Gate

```text
FIRST_OPEN_ENDED_AGENT_CREATED
```

Isso é teste de produto, não benchmark comparativo ou alegação universal.

## Sprint 6 — Casulo VM Controller

### Entregas

- `casulo vm doctor/create/start/stop`;
- QEMU/WHPX/Q35/OVMF pinados;
- base imutável + overlay QCOW2;
- paths confinados;
- QMP local restrito;
- shutdown seguro;
- detecção e recuperação de overlay;
- quota de disco;
- nenhuma mídia física.

### Demo

A VM nasce de forma reproduzível, boota Casulo Native, desliga e reabre preservando owner data sem alterar a base.

### Gate

```text
CASULO_VM_LIFECYCLE_PASS
```

## Sprint 7 — Casulo generativo dentro da VM

### Entregas

- engine owner disponível no guest;
- display/input/storage funcionais;
- áudio por virtio-sound ou bridge first-party limitado;
- ASR/TTS/barge-in;
- fallback textual explícito;
- memória reabre;
- geração T, simulação e materialização dentro do perfil VM;
- comunicação host/guest capability-scoped.

### Demo

Dentro da VM, Guilherme ou um teste de integração conversa com o Guide, cria um agente e o retoma após reboot.

### Gate

```text
GENERATIVE_OWNER_VM_E2E_PASS
```

## Sprint 8 — Primeira interpretação Stark + Jobs

### Entregas

- tema provisório externalizado;
- grande vazio, forma central e estados vivos;
- névoa/âmbar/azul conforme semântica;
- todos os 12 estados;
- renderer dirigido por receipts;
- acessibilidade e reduced motion;
- nenhuma dashboard ou dado decorativo;
- ausência de claim de design final.

### Demo

A criação emerge visualmente durante conversa real na VM; compilação, reparo e simulação têm estados honestos.

### Gate

```text
PROVISIONAL_STARK_JOBS_VM_PASS
```

## Sprint 9 — Ambiente de inspeção de Guilherme

### Entregas

- snapshot/restore/reset de overlay;
- `OwnerInspectionNote` por voz/texto;
- marcação de estado/creation/version;
- categorias de feedback;
- export de feedback sem áudio bruto por default;
- logs sanitizados;
- modo técnico opt-in;
- runbook de uso livre;
- recovery testado.

### Demo

Uma sessão cria nota “a voz está lenta aqui”, associa ao estado correto, restaura snapshot e exporta um pacote legível de feedback.

### Gate

```text
OWNER_INSPECTION_WORKBENCH_PASS
```

## Sprint 10 — Convergência e handoff

### Entregas

- build owner VM reproduzível;
- manifest/SBOM/hashes/assinatura de desenvolvimento;
- suite completa e gates G0–G10;
- image/overlay sizes registrados;
- modelo e licenças registrados;
- launcher e runbook;
- cenário novo final;
- limitações honestas;
- Cloud/public/USB intactos;
- próximo passo definido como inspeção humana.

### Gate automatizado

```text
READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION
```

### Parada obrigatória

O Codex entrega a VM e para. Não inventa aprovação estética ou relacional em nome de Guilherme. Não inicia Live USB. A próxima rodada nasce do feedback real da inspeção.

