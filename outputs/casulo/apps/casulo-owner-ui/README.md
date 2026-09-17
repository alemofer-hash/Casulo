# Casulo Owner UI — Stark + Jobs vertical slice

Primeira casca Tauri 2 do Hosted Product Profile. Ela projeta o contrato
`casulo.owner-ux-event/1.0`; não contém o motor owner, não substitui o Casulo
Native e não executa shell, rede ou filesystem a partir da WebView.

## Validar

```powershell
cd apps/casulo-owner-ui
pnpm check
cargo test --manifest-path src-tauri/Cargo.toml
pnpm tauri build --no-bundle
```

No Windows, o Cargo deste diretório usa o toolchain MSVC já pinado. Se o shell
não localizar `link.exe`, rode o comando dentro de um Developer PowerShell ou
carregue o `VsDevCmd.bat` do Visual Studio Build Tools.

## Inspecionar o design sem motor

```powershell
pnpm dev
```

Abra `http://127.0.0.1:1420`. A interface mostra de modo permanente
`fita sintética · não é runtime`. Cada clique aplica exatamente um evento; não
há timer, ETA ou progresso simulado.

## Conectar o stream owner

O launcher do runtime cria um arquivo append-only sob:

```text
%LOCALAPPDATA%\Casulo\experience\<session>.jsonl
```

Cada linha relevante começa com `CASULO_UX_EVENT ` e carrega o evento canônico
com SHA-256. Defina `CASULO_UX_EVENT_STREAM` para esse caminho antes de iniciar
o executável. O bridge recusa paths relativos, extensões diferentes, symlinks
para fora da raiz, hashes incorretos, streams fora de ordem e jobs sem
evidência.

O slice atual é deliberadamente de saída: entrada de conversa, voz, sidecar e
launcher owner unificado entram em CP4/CP6 depois que a projeção estiver
estável. Um campo visual desabilitado não finge que o motor está conectado.

## Fronteiras

- fontes: somente fontes do sistema;
- assets: somente locais;
- rede runtime: nenhuma;
- plugins Tauri shell/fs/http: nenhum;
- capability da WebView: listen/unlisten de eventos core;
- bundle/installer: ainda desativado;
- modo sintético: nunca aceito como evidência científica ou runtime.
