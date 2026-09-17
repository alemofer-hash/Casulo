# ADR — Tauri 2 como casca Hosted; protocolo visual como fronteira Native

Data: 2026-08-20  
Status: `ACCEPTED_FOR_VERTICAL_SLICE`

## Contexto

O motor Casulo já produz eventos tipados para presença, carregamento do modelo,
stream de tokens e jobs evidenciados. A interface Tkinter prova o fluxo, mas não
oferece a composição, motion, acessibilidade e acabamento necessários. O
protótipo Figma/React possui uma linguagem visual forte, porém usa transições
roteirizadas e não contém uma fronteira de sistema.

## Decisão

Adotar Tauri 2 no Hosted Product Profile com:

- frontend React/Vite reaproveitado seletivamente do protótipo;
- backend Rust mínimo, somente leitura, sem plugin shell/fs/network;
- ingestão de JSONL append-only produzido pelo runtime owner;
- validação do hash e do lifecycle antes de qualquer emissão à WebView;
- capabilities explícitas somente para escutar eventos;
- CSP local e fontes do sistema;
- fita sintética manual e inequivocamente rotulada para inspeção visual.

React permanece porque já existe no protótipo e Tauri é frontend-agnostic.
Trocar para Svelte agora não acrescentaria autoridade, segurança ou qualidade
visual proporcional ao custo de reescrita.

## Fronteira de processo

```text
owner runtime/Python/llama.cpp/T Forge
  -> CASULO_UX_EVENT JSONL append-only
  -> bridge Rust valida schema, hash, ordem e path confinado
  -> evento Tauri casulo://experience
  -> reducer puro
  -> projeção React/CSS/SVG
```

A apresentação não executa sidecar neste slice. O launcher futuro cria o
arquivo de sessão em `%LOCALAPPDATA%\Casulo\experience` e entrega seu caminho ao
Tauri por ambiente herdado. Isso evita shell genérico e mantém o motor atual
intacto. A inclusão de um sidecar empacotado exige outro gate de supply chain.

## Consequências

- o mesmo evento passa a dirigir Tkinter, Tauri e Native;
- Hosted ganha superfície de produto sem se declarar Casulo Native;
- renderer web permanece substituível;
- Rust passa a proteger a fronteira, não a reconstruir decisões do motor;
- `llama.cpp`, T Forge, memória e VM continuam nos processos existentes;
- a etapa Native implementará o reducer e scene graph equivalentes sobre HAL,
  não embarcará WebView2 como se fosse kernel gráfico próprio.

## Segurança

Segundo o modelo de capabilities do Tauri 2, permissões são associadas a
janelas/webviews. Este app habilita explicitamente apenas listen/unlisten de
eventos core. Não há URL remota, iframe, plugin de filesystem, shell, updater,
HTTP ou diálogo. Custom commands têm allowlist de build e validam todos os
dados no Rust; capabilities não tornam código Rust inseguro automaticamente.

## Decisões adiadas

- Rive: só depois de licença/runtime/hash e orçamento medido;
- voz física: continua no adapter já existente, fora deste Sprint;
- sidecar empacotado e installer: CP12;
- renderer Native: inicia após estabilização do scene schema;
- design final: revisão humana de Guilherme.
