# Relatório — Stark + Jobs Tauri vertical slice

Data: 2026-08-20  
Estado técnico: `STARK_JOBS_TAURI_VERTICAL_SLICE_PASS`  
Design/beleza/química: `PROVISIONAL_OWNER_REVIEW_REQUIRED`

## Resultado principal

O protótipo Figma deixou de ser apenas uma navegação roteirizada e originou uma
casca Tauri 2 executável. A nova superfície preserva sua linguagem de presença,
forma viva, âmbar/cobalto/ivory e simplicidade, mas o estado agora vem do
contrato owner real. Tokens são acrescentados conforme `ASSISTANT_TOKEN` chega;
jobs só evoluem com eventos contendo SHA-256 de evidência.

O frontend não possui timer de produto, URL remota, `fetch`, WebSocket, plugin
shell, plugin fs ou fonte externa. A fita sintética existe apenas no build web
de inspeção, avança por clique e carrega o rótulo permanente “não é runtime”.

## Código entregue

- `apps/casulo-owner-ui`: React/Vite/Tauri 2 pinado;
- `src/experience.mjs`: validator/reducer imutável;
- `src-tauri/src/lib.rs`: bridge append-only, hash canônico e lifecycle;
- `src/LivingForm.tsx`: scene SVG derivada de evidências;
- `schemas/product/stark-jobs-scene-v1.json`: fronteira visual;
- `STARK_JOBS_TAURI_ADR.md`: decisão Hosted;
- `STARK_JOBS_NATIVE_PROMOTION_PLAN.md`: promoção ao OS.

## Gates executados

| Gate | Resultado |
| --- | --- |
| Node reducer | 6/6 PASS |
| Rust bridge | 5/5 PASS |
| evento criado pelo runtime Python aceito no Rust | PASS |
| adulteração/hash incorreto | REJECTED |
| progresso percentual/ETA fabricado | REJECTED |
| token fora de ordem | REJECTED |
| conclusão após cancelamento | REJECTED |
| pytest do contrato/stream/Creation Field | 20/20 PASS |
| regressão completa `tests/product` | 524 PASS, 1 skip físico/ambiental preservado |
| TypeScript | PASS |
| Vite production build | PASS |
| supply-chain audit npm | zero vulnerabilidade conhecida |
| source audit | network=false, shell=false, fs=false, timer=false |
| Tauri MSVC release | PASS |
| executável iniciou por smoke de 3 s | PASS |

## Build

```text
dist/index.html                 0,58 kB
dist/assets/*.css             10,30 kB (3,37 kB gzip)
dist/assets/*.js             207,78 kB (65,98 kB gzip)
casulo-owner-ui.exe        8.718.848 bytes
SHA-256                    3f3b867aa8a94c784ce48f2a9f0ebf2910b1ca98a8b75721a5024b915d9f3e35
```

Lockfiles:

- pnpm: `b696cfa598a03a7041bb7365ec30c0099ee353a79d7814bb058e83a96fb29d27`;
- Cargo: `e5f63025420577d5f38b6610ea592303ca765459ba336bfda9aa85f265926e28`;
- scene schema: `804ceb12b510f250cfd41a6e49185fe8db73f13c09a7f3288703368889435a8d`.

## Inspeção visual

| Verificação | Resultado |
| --- | --- |
| viewport 1280x720 | `scrollWidth=innerWidth`, `scrollHeight=innerHeight` |
| viewport 1440x900 | `scrollWidth=innerWidth`, `scrollHeight=innerHeight` |
| recursos remotos DOM | zero |
| console errors/warnings | zero |
| stream parcial | texto parcial + cursor; mensagem ainda não terminal |
| materialização | forma e card derivados de 2 milestone receipts |
| drawer | `role=dialog`, foco inicial, Escape fecha |
| reduced motion | media query e modo imóvel explícitos |

Contrastes estáticos contra `ink #070a12`:

- ivory: `18,61:1`;
- mist: `11,86:1`;
- amber: `9,08:1`;
- boundary text: `8,51:1`;
- muted: `7,24:1`.

## Divergências encontradas e corrigidas

1. Cargo default usava GNU/MinGW e falhou no WebView2 com `export ordinal too
   large`; o app foi pinado ao MSVC já instalado, sem alterar o Native nightly.
2. `tauri-build` exigia um ícone Windows; foi criado um asset vetorial Casulo
   original e os ícones foram gerados pela CLI oficial.
3. O hash Python inclui newline no JSON canônico; o primeiro Rust self-test não
   captou isso. Uma fixture realmente produzida por `UxEvent.create` expôs a
   divergência, que foi corrigida sem reduzir validação.
4. O tailer inicialmente começava antes de a WebView escutar. Agora a UI
   registra listeners e só então chama `start_bridge`, impedindo perda inicial.
5. Stream configurado inválido agora vira `CONFIGURATION_REJECTED`; não é
   confundido com ausência de stream.
6. A primeira regressão Python integral foi invocada da subpasta do app e
   falhou na coleta de seis imports `tools.*`. A mesma suíte foi repetida da
   raiz real, sem mudança de código, e concluiu `524 passed, 1 skipped`.

## Dependências e disco

Foram instalados apenas no workspace 29 pacotes npm resolvidos por lock. Cargo
selou 428 crates transitivas. Nenhum pacote global, driver, modelo, voz, fonte
ou plugin de acesso ao sistema foi instalado. Espaço livre final observado:
`63,29 GiB` no fechamento, acima da reserva de 25 GiB.

Os targets Cargo debug/GNU gerados pela primeira compilação permanecem como
cache ignorado pelo Git; podem ser removidos mais tarde por uma limpeza
confinada, sem tocar no source ou no executável release. A tentativa automática
de limpeza foi recusada pela política do ambiente, portanto nenhum diretório
foi apagado silenciosamente.

## Limitações honestas

- a entrada visual ainda não envia turnos ao motor; este slice é a ponte de
  saída e projeção de CP1;
- o launcher owner existente ainda não inicia Tauri e runtime como uma unidade;
- voz, barge-in e qualidade humana não foram exercidos;
- Rive não foi adotado; a forma atual é SVG/CSS local;
- não há installer/bundle, assinatura de release ou execução sem a árvore;
- Tauri é Hosted, não o Casulo Native;
- fita sintética valida reducer/design, não geração neural;
- prazer, beleza e química aguardam Guilherme.

## Próximo passo exato

Executar CP4 como um serviço owner persistente com canal de entrada tipado e
stream de saída já conectado ao bridge. Depois, CP5 liga correção do espelho;
somente quando o scene schema estabilizar começa NUI0 do plano Native.
