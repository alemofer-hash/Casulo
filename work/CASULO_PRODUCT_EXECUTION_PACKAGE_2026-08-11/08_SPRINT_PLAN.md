# PLANO DE SPRINTS

## Regra geral

Sprints são sequenciais por dependência, não necessariamente por calendário. Paralelizar apenas arquivos/subsistemas sem conflito e sem violar `AGENTS.md`.

## Sprint 0 — Transição e auditoria

### Objetivo

Conhecer o repositório real e remover benchmark científico do caminho crítico sem apagar evidência.

### Entregas

- inventário de árvore, toolchains, locks e testes;
- baseline de testes existentes;
- ADR de transição;
- GOAL antigo marcado superseded;
- `T_GAP_AUDIT.md`;
- `DEPENDENCY_LEDGER.md`;
- `EXECUTION_STATE.md`;
- workflows científicos fora do default;
- comandos longos com trava explícita.

### Gate

Build/test default não inicia benchmark, RAPL, HWiNFO, PyTorch ou campanha térmica.

## Sprint 1 — Constituição executável e modelo de domínio

### Entregas

- `CreationSpec`, `IntentDelta`, `CollaborationContract`, `MemoryPolicy`, `CapabilityGrant`;
- schemas versionados;
- serialização canônica;
- state machine dos 12 estados;
- migrações e validação;
- testes de invariantes.

### Demo

CLI/teste cria uma criação, aplica delta, rejeita aumento de permissão e reidrata versão.

## Sprint 2 — Platform contracts e Hosted Shell

### Entregas

- HAL comum;
- implementações hosted mínimas de clock, storage, process, audio e display;
- shell preto/minimalista;
- core visual vivo;
- event loop sem mouse obrigatório;
- feature flags minimal/voice/guide/creator.

### Demo

Casulo abre no estado `SILENCE` e reage a evento de voz sintético.

## Sprint 3 — T vNext Foundations

### Entregas

- congelar T 1.0/goldens;
- expression AST própria;
- records/enums/result;
- resolução real de módulos;
- effect/capability RFC e checker mínimo;
- IR vNext com CFG suficiente;
- `.tcap` versionado.

### Demo

Programa T com memória/capability permitida compila; capability ausente falha com diagnóstico claro.

## Sprint 4 — Living Memory

### Entregas

- event log append-only;
- projeções episódica/semântica/criação/colaboração;
- proveniência;
- busca lexical + vetorial local simples;
- criptografia/secrets;
- export/delete;
- “lembra daquilo?” com desambiguação.

### Demo

Fechar processo, reabrir e retomar criação com decisão, motivo e ponto pendente corretos.

## Sprint 5 — Voice Duplex

### Entregas

- captura/playback;
- VAD;
- ASR streaming local;
- partial/final transcript;
- endpointing configurável;
- TTS streaming local;
- barge-in abaixo do budget definido pelo hardware;
- fallback texto/acessibilidade.

### Demo

Conversa pt-BR contínua; usuário interrompe fala do Guia e a resposta para imediatamente sem perder o fio.

## Sprint 6 — Guide Presence

### Entregas

- dialogue loop;
- collaboration model;
- consentimento de adaptações;
- modo expansão/cristalização;
- política de esclarecimento;
- background conversation;
- progress milestones reais;
- prevenção de bajulação e pressão artificial nos testes de contrato.

### Demo

Worker de 2–5 minutos simulado roda; Guia continua conversa relevante e reporta somente eventos reais.

## Sprint 7 — Intent Engine e T Forge incremental

### Entregas

- fala -> `IntentDelta`;
- constraint merge;
- base version/conflict;
- impact analysis;
- patch T/IR/graph;
- testes afetados;
- hash preservation fora do impacto.

### Demo

“Está formal demais” altera somente personalidade/comunicação e preserva capabilities, memória e lógica.

## Sprint 8 — Creation Field

### Entregas

- `VisualSemanticModel`;
- renderer hosted;
- 12 estados;
- semântica névoa/âmbar/azul;
- degradação adaptativa;
- visual regression tests;
- áudio/voz com prioridade sobre render.

### Demo

Sequência da primeira intenção à confirmação surge em tempo real; correção é localizada visualmente.

## Sprint 9 — Simulation Runtime

### Entregas

- relógio virtual;
- fake capabilities;
- cenários;
- failure injection;
- pause/interruption;
- replay;
- comparação de versões;
- zero efeito real.

### Demo

Agente tenta ação proibida, é bloqueado, Guia explica e Inventor altera o contrato.

## Sprint 10 — Local Intelligence Stack

### Entregas

- model registry;
- hashes/licenças/model cards;
- adapter local LLM/embeddings;
- roteamento por hardware;
- memory/context selection;
- isolamento de parser/model files;
- caminho para modelos especializados Casulo;
- nenhuma API externa obrigatória.

### Demo

Máquina offline cria e revisa um agente simples com modelo local.

## Sprint 11 — Materializer

### Entregas

- pacote Casulo;
- API HTTP local;
- processo local;
- OCI opcional;
- MCP opcional;
- manifest, SBOM, hashes;
- secret exclusion;
- sandbox tests;
- import/reedição.

### Demo

Criação sai do Casulo, roda como API local, é importada novamente e mantém identidade/versão.

## Sprint 12 — Installer e Machine Profile

### Entregas

- `doctor` somente leitura;
- terminal de instalação minimalista;
- escolha de pacotes compatíveis;
- consentimento de downloads;
- calibração leve;
- estimativa de duração;
- primeiro encontro com Guia;
- sem cadastro obrigatório.

### Demo

Instalação limpa em VM supported, primeiro boot e primeira conversa.

## Sprint 13 — Casulo Native Foundation

### Entregas

- boot UEFI QEMU/OVMF;
- memória, timer, ring 3, syscalls e IPC mínimos;
- loader `.tcap`;
- processo isolado;
- HAL native inicial;
- serial/framebuffer;
- imagem virtual e hashes;
- zero escrita automática em disco real.

### Demo

Native boota, valida e executa artefato T isolado, produz trace e desliga com segurança.

## Sprint 14 — Convergência e Product Alpha

### Entregas

- vertical slice end-to-end;
- budgets de UX calibrados por máquina;
- threat model e fuzzing;
- acessibilidade;
- recovery/backup;
- release manifest;
- demo runbook;
- lista explícita do que ainda é hosted;
- roadmap de drivers native.

### Gate

Todos os P0–P13 de `09_ACCEPTANCE_TESTS.md` aprovados.

## Pós-Alpha — não bloquear o Alpha

- áudio native amplo;
- drivers GPU native;
- networking native completo;
- modelos/vozes próprios;
- treino e pós-treino Casulo;
- hardware certification matrix;
- marketplace opcional;
- targets móveis;
- sync opcional criptografado.

