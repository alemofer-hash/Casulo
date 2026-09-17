# Plano de promoção Stark + Jobs para o código do Casulo Native/OS

Data: 2026-08-20  
Origem: vertical slice Tauri 2 `apps/casulo-owner-ui`  
Estado: `PLAN_FROZEN_AFTER_HOSTED_VERTICAL_SLICE`

## Resultado que será promovido

O design não é React, CSS ou Tauri. O elemento portátil é a relação causal:

```text
evento owner validado
-> reducer de apresentação puro
-> scene state limitado
-> forma, conversa e evidência projetadas
```

Tauri/WebView2 continua sendo a superfície Hosted para validar experiência e
acabamento. O Casulo Native implementará outro adapter do mesmo contrato. Não
será usado WebView2 dentro do kernel, e a Native Foundation atual não será
apresentada como SO gráfico completo antes de drivers, compositor e input reais.

## Fontes de verdade

| Contrato | Função | Consumidor atual | Consumidor Native |
| --- | --- | --- | --- |
| `schemas/product/hosted-native-ux-contract-v1.json` | wire/lifecycle e prioridades | Python, Tauri Rust, kernel | `product_runtime.rs` |
| `schemas/product/stark-jobs-scene-v1.json` | formas e autoridade zero da UI | reducer JS | novo `presentation::projector` |
| `src/casulo/product/pleasant_interface.py` | encoder/validator Hosted | runtime owner | oráculo de conformance |
| `apps/casulo-owner-ui/src/experience.mjs` | projeção Hosted | React | oráculo comportamental, não código copiado |
| `os/kernel/src/product_runtime.rs` | lifecycle bounded no_std | QEMU/Native | entrada do projector |

## Arquitetura Native desejada

```text
TCAP / Guide / jobs
        |
        v
NativeEventLoop (já existe; PRESENCE prioritária)
        |
        v
PresentationProjector <--- scene-v1 gerado e selado
        |
        v
SceneState bounded
  form + text spans + nodes + receipts + focus
        |
        +------> SerialRenderer (oráculo CI)
        +------> GopFramebufferRenderer (QEMU/UEFI)
        +------> futuro GPU adapter (não gate inicial)
```

O compositor recebe estado; não eventos crus e não output neural não validado.
A fila de apresentação nunca cria grants, receipts ou conclusão.

## Sequência de implementação

### NUI0 — Congelar contrato e replay dourado

**Mudanças:** gerar uma fita pequena de eventos canônicos Python; selar hash do
contrato e do scene schema; produzir o mesmo snapshot semântico em JS e Rust
`std`.

**Gate:** estado final, recusas e ordem coincidem; nenhum screenshot é usado
como substituto da semântica.

### NUI1 — Scene IR bounded em `no_std`

**Arquivos propostos:**

```text
os/kernel/src/presentation/mod.rs
os/kernel/src/presentation/scene.rs
os/kernel/src/presentation/projector.rs
os/kernel/src/presentation/text.rs
```

`SceneState` usa arrays fixos e limites explícitos: até 16 nós visuais, 16
receipts visíveis, uma mensagem streaming limitada a 8 KiB e uma falha
recuperável. IDs internos usam hashes/inteiros; texto UTF-8 é truncado somente
com evento visual de continuação, nunca em silêncio.

**Gate:** overflow produz `CapacityExceeded` sem corromper o estado anterior.

### NUI2 — Autoridade e conformance geradas

Adicionar um gerador read-only que converta os dois JSONs em constantes Rust
para Hosted bridge e Native. O código gerado carrega os SHA-256 dos arquivos de
origem. Não haverá três listas de eventos mantidas manualmente.

**Gate:** CI falha se Python, Tauri ou Native divergirem em kind, limite,
projeção ou hash.

### NUI3 — Framebuffer mínimo original

Acrescentar à HAL uma superfície 2D abstrata e implementar primeiro o adapter
UEFI GOP/QEMU:

```text
clear / rect / rounded_rect / line / circle / glyph / clip / present
```

O visual Stark + Jobs é refeito com primitives Casulo: fundo ink, campo azul,
núcleo âmbar, threads e nós derivados de receipts. Nada depende de asset ou
marca de terceiros. Motion usa relógio monotônico somente para interpolação
entre dois estados autorizados; não sintetiza progresso.

**Gate:** framebuffer de teste produz hash estável em estado imóvel; transição
é desativável por reduced motion.

### NUI4 — Texto, input e acessibilidade

Adotar um atlas de glifos local com licença registrada; até essa decisão, usar
uma fonte bitmap técnica somente em CI. Implementar foco, teclado, contraste
alto e reduced motion na HAL. Voz continua adapter separado e não bloqueia
texto/input básico.

**Gate:** todas as ações essenciais funcionam por teclado; nenhum glyph/font é
adotado sem licença/hash/SBOM.

### NUI5 — Presence e stream no scheduler

Ligar `ASSISTANT_START/TOKEN/END` ao projector mantendo `PRESENCE` acima de
`BACKGROUND`. Tokens são pintados quando consumidos da fila. O render loop
possui budget e cede CPU ao modelo/worker; a forma estável não redesenha em
loop contínuo.

**Gate:** token fora de ordem e conclusão tardia são recusados antes do scene;
idle não causa redraw; job em background não congela input.

### NUI6 — Ponte Hosted/Native durante a convergência

Enquanto modelo, ASR/TTS, DPAPI, T Forge e materializador continuarem Hosted, a
VM recebe somente o stream tipado pelo transport já autenticado. Nenhum stdout,
path do host ou conteúdo arbitrário entra como instrução. A base VM permanece
read-only e guest network OFF.

**Gate:** desconexão deixa a última cena válida recuperável; reconexão reidrata
por replay idempotente; zero block device real.

### NUI7 — Paridade visual delimitada e handoff

Executar a mesma fita em Tauri e Native e comparar:

- scene state canônico: igualdade obrigatória;
- acessibilidade/labels: equivalência operacional;
- imagem: comparação perceptual com tolerância congelada, não identidade de
  pixels entre renderers;
- latência de input e frame budget: micro-medição de UX, não benchmark
  científico.

**Gate:** três rotas — conversa, criação e falha recuperável — passam em QEMU;
Guilherme avalia beleza e prazer na VM. O gate automático não aprova estética.

## O que não será portado

- DOM, React, Vite, CSS e Tauri;
- timers de animação como fonte de estado;
- fita sintética como runtime;
- Google Fonts, assets remotos ou runtime Rive sem adoção;
- shell, filesystem ou rede genéricos;
- controls técnicos como caminho principal;
- inferência, voz ou materialização fingidas dentro do kernel.

## Orçamento de risco

| Risco | Mitigação |
| --- | --- |
| renderer competir com inferência em 16 GiB | scene bounded, redraw por dano, idle imóvel, sem Chromium Native |
| divergência Hosted/Native | schema gerado + replay dourado + hashes |
| motion virar progresso falso | motion só interpola estados já aceitos |
| texto/Unicode ampliar memória | buffers limitados e continuação explícita |
| UI receber autoridade | capability broker e publisher permanecem fora do renderer |
| tentar terminar todos os drivers de uma vez | GOP/QEMU primeiro; GPU/áudio continuam adapters futuros |

## Critério de promoção ao SO

O design pode ser chamado parte do código do Casulo Native somente quando:

1. `SceneState` e projector rodarem dentro do kernel/fundação Native;
2. o mesmo replay do owner produzir estado semanticamente equivalente;
3. framebuffer e input funcionarem em QEMU sem rede e sem device real;
4. stream/cancelamento preservarem invariantes;
5. nenhum estado visual existir sem evento ou receipt autorizador;
6. a VM permitir a Guilherme conversar e acompanhar uma criação, ainda que os
   adapters pesados permaneçam Hosted.

Até lá, a formulação correta é: **Stark + Jobs está implementado na nova casca
Hosted Tauri e possui um contrato explícito de convergência para Native.**
