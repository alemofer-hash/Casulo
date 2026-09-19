# Ledger de dependências

Inventário em 2026-08-11. O ASR local descrito abaixo foi adotado após
autorização; nenhum driver, voz redistribuível ou engine TTS foi instalado.

O Sprint 3 foi implementado apenas com a biblioteca padrão já disponível. Não
adicionou dependência, download, driver, modelo ou voz.

O Sprint 4 também não adicionou pacote. A criptografia hosted usa DPAPI nativa
do Windows via `ctypes`; busca lexical/vetorial é implementação local
determinística, não modelo de embedding.

## Toolchains observadas

| Ferramenta | Estado |
|---|---|
| Python | 3.13.2 |
| Git | 2.54.0.windows.1 |
| Rust/Cargo host | 1.93.0 |
| Rust native pin | nightly-2026-02-01 |
| Node | 22.14.0 |
| CMake | 4.3.2 |
| Ninja | 1.13.2 |
| Clang | LLVM 22.1.8 instalado em `C:\Program Files\LLVM`; detectado pelo Machine Profile |
| QEMU x86-64 | 11.0.50 instalado em `C:\Program Files\qemu`; OVMF x86-64 detectado |

## Manifests/locks existentes

| Arquivo | SHA-256 | Observação |
|---|---|---|
| `pyproject.toml` (pré-transição) | `5D975AA2CD6969D22850D21550D8298F5CAA4080F40FF6C54FD430758C2E3FC7` | ranges, não lock completo |
| `os/Cargo.lock` | `0AAF3AEE08EA6ACBB1A17A9A6B1596CAF744DE5C36D940BCDB2974EECD2EE204` | lock native existente |
| `release/requirements-rp01.lock` | `BF90F648DAD13BD700E039D698E4B4F360CDB7A066C6FB0340F95044AA31EE03` | Research Preview; não default |
| `examples/t-project-training/casulo.lock` | registrado pelo workspace T | exemplo histórico |

## Python

O core declara zero dependências obrigatórias. `build`, `hypothesis`, `pytest`,
`pytest-cov` e `twine` compõem desenvolvimento. `numpy`, `torch`, `psutil` e
`pyperf` pertencem ao arquivo `legacy-research`; não são instalados pelo CI ou
release padrão do produto. As versões são ranges no `pyproject.toml`, portanto
um lock de produto ainda precisa ser escolhido antes de release.

## Rust native

`bootloader = 0.11.15` está pinado no workspace e no Cargo.lock. Licenças e
cadeia completa precisam ser extraídas para `THIRD_PARTY_NOTICES.md`/SBOM antes
de release; este Sprint não inferiu licenças sem fonte do lock.

## Candidatos ainda não adotados

`llama.cpp`, engine/voz TTS, `wgpu`, `winit`, `cpal`, SQLite
bindings, runtime async e TLS são candidatos, não dependências. Adoção exige
fonte oficial, versão/commit, hash, licença, card quando aplicável e consentimento
para download. TTS permanece sem decisão de licença.

## Preflight de voz 2026-08-11

- `sounddevice 0.5.5`, licença declarada `MIT`, já presente; ainda não pinado;
- Microsoft Maria Desktop pt-BR, componente do sistema, fallback opcional;
- reconhecedor Windows disponível apenas en-US, rejeitado para o gate pt-BR;
- `whisper.cpp`/modelo small foi adotado depois deste preflight;
- nenhum ffmpeg, voz redistribuível ou engine TTS foi instalado.

Candidate manifest imutável criado para `whisper.cpp v1.9.2`, commit
`306c88f4d1286aec1bf96e544632897886af5501`, MIT; modelo multilingual
`small-q5_1`, 190.085.487 bytes, SHA-256
`ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb`.
O estado do host fica em `ADOPTION.json`, não é falsificado no manifesto:
source/commit e modelo/hash passaram, o bridge possui SHA-256
`4aa83dba47f92d25d3c6a6c3b3e024d67e0bad2760eab49c60ffe9005233a73c`.

Perfil rápido adicional adotado no mesmo source: `ggml-base-q5_1.bin`,
59.707.625 bytes, SHA-256
`422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898`,
MIT declarado pelo repositório oficial. Receipts por modelo impedem que a
adoção do perfil rápido apague a proveniência do perfil small.

O boundary `casulo-asr-command/1.0` e o `casulo-voice doctor` usam somente a
biblioteca padrão. O doctor não cria cache, não acessa rede e só considera o
ASR pronto quando source receipt, modelo com tamanho/hash exatos e bridge
first-party estiverem presentes e a ABI puder ser carregada. O doctor atual
retorna `READY` neste host.

O source nativo first-party em `native/voice` usa somente a API C pinada do
upstream e desativa tests, examples, server, CURL, SDL2, OpenVINO e CoreML no
build local inicial. A checagem de ABI compilou contra stub com o `g++` já
presente; depois da autorização, upstream/modelo foram instalados e o bridge
foi compilado estaticamente contra os runtimes MinGW, sem DLL não sistêmica.
O comando `adopt-asr` é o único
caminho com rede e exige a frase literal registrada; `doctor` e `build-asr`
nunca baixam conteúdo.

Microsoft Maria possui card próprio em
`release/voice-candidates/microsoft-maria-system.json`: componente do Windows,
não redistribuído, sem model hash controlado pelo Casulo e desabilitado por
padrão. O smoke local gerou 90.944 bytes PCM16 em memória. A tentativa de
streaming direto foi rejeitada porque `System.Speech` exige stream seekable;
o fallback correto é buffered e declara `streaming=false`.

A rota separada
`release/voice-candidates/microsoft-maria-direct-system.json` usa playback SAPI
progressivo e cancelável, declara `streaming_playback=true`,
`streaming_pcm=false` e `redistributed=false`. Não adiciona pacote nem peso e
aguarda smoke físico consentido.

Auditoria TTS adicional: Piper ativo (`piper1-gpl`) é GPL-3.0. O candidato
`sherpa-onnx` v1.13.5 é Apache-2.0 no topo, mas seu build TTS inclui eSpeak NG
GPL-3.0-or-later e piper-phonemize. A voz Edresson low possui card com corpus
CC BY 4.0. O conjunto ficou `LICENSE_REVIEW_REQUIRED_NOT_ADOPTED`, pinado apenas
para revisão em `release/voice-candidates/tts-sherpa-edresson-license-review.json`.
Nenhum download ocorreu.

## Installer e Machine Profile

O Sprint 12 nao adiciona dependencia de runtime. Deteccao de CPU, memoria,
disco, Python e toolchains usa apenas a biblioteca padrao. O perfil de voz
reutiliza o manifest, hashes, licencas e doctor read-only ja registrados. A
microcalibracao e limitada a 250 ms, serve somente para estimativa de UX local e
declara `scientific_benchmark=false`.

## Product Alpha: modelos e assinatura

- `models/first-party/casulo-guide-policy-v1.json`: política determinística
  first-party, sem rede e sem pesos de terceiros;
- `models/first-party/casulo-exact-embedding-v1.json`: embedding exato/hash de
  referência, sem alegação neural;
- `models/registry.json`: hashes, ownership, licença e flags de uso/treino;
- Ed25519 de desenvolvimento: chaves privadas foram geradas fora do repositório
  em `%LOCALAPPDATA%\\Casulo\\dev-signing`; artefatos recebem apenas chave
  pública, assinatura, manifest e SBOM;
- LLVM 22.1.8 e QEMU 11.0.50 são ferramentas do host para o gate Native, não
  dependências distribuídas no cliente public.

Antes de qualquer release comercial, as chaves de desenvolvimento devem ser
substituídas por uma cadeia de assinatura de release sob procedimento separado.

## Family RP0.1 — Dia 5: memória e RAG

Nenhum pacote ou serviço de runtime foi adicionado. A persistência e a busca
lexical usam `sqlite3` da biblioteca padrão do Python (SQLite 3.45.3 com FTS5),
em loopback/local e sem rede. O embedding first-party
`casulo-exact-embedding-v1` é uma projeção signed-hash determinística de 64
dimensões, declarada `LicenseRef-Teloscorp-Proprietary`, sem pesos externos e
sem alegação neural. Seu card é pinado pelo SHA-256
`0876987a6ef2ab29f4a93d0b3947b4b08fd3931466c086a90be1978435d36961`.

Origem, limites e rollback estão registrados em
`config/family/day5-dependencies.json` e `config/family/day5-rag-policy.json`.
Rollback funcional: parar o Gateway, preservar o banco para exportação e
reverter o commit do Dia 5; nenhuma instalação global precisa ser removida.

## Stark + Jobs Tauri vertical slice — preflight 2026-08-20

O Sprint usa somente dependências locais ao workspace
`apps/casulo-owner-ui`. Nenhum pacote global, driver, modelo, voz, fonte ou
plugin de acesso ao sistema será instalado.

| Dependência | Versão pinada | Licença declarada | Papel | Estimativa inicial |
| --- | ---: | --- | --- | ---: |
| `tauri` crate | 2.11.5 | Apache-2.0 OR MIT | janela/bridge Hosted | cache Cargo compartilhado; até 300 MiB no pico |
| `tauri-build` | 2.6.3 | Apache-2.0 OR MIT | build metadata/ACL | incluído no pico Cargo |
| `@tauri-apps/api` | 2.11.1 | Apache-2.0 OR MIT | listen/invoke tipado | 0,70 MiB desempacotado |
| `@tauri-apps/cli` | 2.11.4 | Apache-2.0 OR MIT | CLI local do app | binário por plataforma, sem instalação global |
| React / React DOM | 19.2.8 | MIT | projeção visual | abaixo de 1 MiB por pacote |
| Vite | 8.2.2 | MIT | build frontend | dev-only |
| React plugin Vite | 6.1.0 | MIT | build JSX | dev-only |
| TypeScript | 7.0.2 | Apache-2.0 | checagem estática | dev-only |

Toolchains observadas: Rust/Cargo 1.93.0, Node 22.14.0, pnpm 11.19.0,
MSVC 19.44 e WebView2 151.0.4129.93. O host possuía 70,87 GiB livres antes da
instalação. A reserva operacional de 25 GiB permanece satisfeita mesmo sob uma
estimativa conservadora inferior a 1 GiB de pico. As versões e hashes efetivos
do lock/SBOM serão registrados depois da resolução; esta tabela não substitui
os lockfiles.

Resolução efetiva: 29 pacotes npm no workspace, zero vulnerabilidade conhecida
no audit executado e 428 crates Cargo transitivas. Lock pnpm SHA-256
`b696cfa598a03a7041bb7365ec30c0099ee353a79d7814bb058e83a96fb29d27`;
lock Cargo SHA-256
`e5f63025420577d5f38b6610ea592303ca765459ba336bfda9aa85f265926e28`.
O host já possuía `stable-x86_64-pc-windows-msvc`; o app apenas o seleciona por
`rust-toolchain.toml`. O default GNU preservado no host não foi alterado.
