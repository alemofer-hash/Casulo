# DEPENDÊNCIAS E REQUIREMENTS DE INSTALAÇÃO

## 1. Política

O repositório atual é a fonte de verdade para versões. O Sprint 0 deve inventariar locks existentes antes de fixar qualquer versão nova.

Regras:

- toda dependência é pinada por versão/commit e hash;
- toda licença entra em `THIRD_PARTY_NOTICES` e SBOM;
- pesos têm model card, licença e hash próprios;
- dependência de bootstrap fica atrás de interface substituível;
- nenhuma API comercial externa é requisito;
- downloads ocorrem na instalação/build com consentimento, nunca secretamente;
- artefatos de release podem ser construídos offline após cache completo.

## 2. Hardware

### Desenvolvimento mínimo realista

- CPU x86-64 com virtualização;
- 16 GB RAM;
- 40 GB livres para código, builds, firmware e modelos pequenos;
- microfone e saída de áudio;
- GPU opcional;
- firmware UEFI para testes físicos futuros.

### Recomendado para experiência local confortável

- 32 GB RAM;
- SSD com 100 GB livres;
- GPU com 8 GB ou mais de VRAM, ou CPU moderna com instruções vetoriais;
- microfone com cancelamento de ruído razoável.

Máquinas menores devem receber modelos, renderização e tarefas adaptados. O sistema não promete a mesma latência em todo hardware.

## 3. Host de desenvolvimento recomendado

Primeiro alvo reproduzível:

- Linux x86-64 recente, nativo ou VM com virtualização aninhada quando suportada;
- Windows pode usar ambiente Linux de desenvolvimento, mas áudio/GPU do produto hosted deve também ser testado nativamente;
- macOS é alvo hosted posterior; Casulo Native inicial permanece x86-64/UEFI.

## 4. Toolchain obrigatório

### Geral

- Git;
- CMake;
- Ninja;
- Clang/LLVM + LLD;
- GCC para paridade quando já utilizado;
- pkg-config;
- Python compatível com o projeto (`>=3.11` no snapshot histórico);
- venv/uv ou gerenciador já adotado no repositório;
- Rust estável pinado em `rust-toolchain.toml`;
- cargo-deny/cargo-audit ou equivalentes;
- Syft/Trivy ou equivalente para SBOM/vulnerabilidades no release.

### Native OS

- QEMU x86-64;
- OVMF/TianoCore;
- mtools;
- dosfstools;
- xorriso quando necessário ao formato de imagem;
- GDB/LLDB;
- binutils/objdump/readelf;
- bootloader escolhido após auditoria (preservar o existente; Limine apenas se ainda for a decisão válida).

QEMU + OVMF são o caminho padrão para validar UEFI antes de hardware físico: https://rust-osdev.github.io/uefi-rs/tutorial/vm.html

## 5. Runtime e interface

### Rust — candidatos a confirmar e pinar

- `tokio` ou runtime async já adotado;
- `serde` + formato canônico definido pelo projeto;
- `tracing`;
- `thiserror`/`miette` para diagnósticos;
- `wgpu` para renderer hosted;
- `winit` para janela/eventos hosted;
- `cpal` para áudio cross-platform hosted;
- `rusqlite` ou binding equivalente para SQLite;
- `rustls` para rede opcional;
- `axum`/`hyper` para API materializada;
- `wasmtime` apenas se WASI for aceito como target;
- `ring` ou `ed25519-dalek` para assinatura conforme threat model.

`wgpu` oferece backends nativos Vulkan, Metal e DirectX 12, mas não resolve o driver gráfico do Casulo Native: https://wgpu.rs/index.html

## 6. Inteligência local — bootstrap

### LLM/embeddings

Adapter candidato: `llama.cpp`, pinado por commit, construído como biblioteca, nunca controlado por shell textual em produção.

Motivos:

- inferência local;
- CPU e backends CUDA/HIP/Vulkan/SYCL;
- quantização;
- execução híbrida CPU/GPU;
- formato GGUF.

Fonte oficial: https://github.com/ggml-org/llama.cpp

Requisitos adicionais:

- registry interno de modelos;
- allowlist de arquiteturas;
- hashes;
- model cards;
- verificação de licença;
- limites de RAM/VRAM;
- isolamento do parser GGUF;
- nenhum download automático sem consentimento.

### ASR

Adapter candidato: `whisper.cpp`, pinado por commit, com interface streaming própria do Casulo.

Fonte oficial: https://github.com/ggml-org/whisper.cpp

O exemplo upstream de streaming é referência, não contrato de produção. O Casulo precisa implementar VAD, endpointing, barge-in, confiança e testes de português brasileiro.

### TTS

Não congelar Piper antigo automaticamente: o repositório histórico foi arquivado em 2025 e o desenvolvimento apontou para um sucessor com licença diferente. A escolha exige auditoria de licença do engine e de cada voz.

Contrato obrigatório:

- `TtsEngine` substituível;
- streaming PCM;
- cancelamento imediato;
- pt-BR;
- model/voice card;
- licença redistribuível;
- fallback de voz do sistema no perfil hosted apenas como opção.

## 7. Memória

Baseline de produto:

- SQLite local com WAL;
- FTS5 para busca lexical;
- blobs endereçados por conteúdo;
- índice vetorial interno simples inicialmente (busca exata/brute force para correção);
- HNSW apenas depois de testes de persistência, migração e exclusão;
- criptografia de secrets separada do banco;
- backup/export e delete verificável.

Evitar introduzir servidor de banco, Redis, Elasticsearch ou vector DB externo no caminho local inicial.

## 8. Dependências Python históricas

Snapshot `0.25.0a1`:

```text
python >= 3.11
numpy >= 2.3,<3       [ml/parity]
torch >= 2.12,<3      [ml/parity]
psutil >= 7.2,<8      [science]
pyperf >= 2.10,<3     [science]
hypothesis >= 6.163,<7
pytest >= 9.1,<10
pytest-cov >= 7.1,<8
```

Decisão nova:

- `torch`, `pyperf`, RAPL e tooling científico deixam de ser instalação padrão;
- permanecem apenas no grupo `legacy-research`, se ainda necessário para reproduzir o arquivo histórico;
- compilador de referência e testes T mantêm apenas dependências realmente usadas;
- o Sprint 0 deve separar extras sem quebrar o arquivo histórico.

## 9. Layout de manifests recomendado

```text
rust-toolchain.toml
Cargo.toml
Cargo.lock
pyproject.toml
uv.lock ou lock equivalente
cmake/third_party.cmake
models/registry.toml
models/LOCK.json
THIRD_PARTY_NOTICES.md
sbom/
```

## 10. Instalação de desenvolvimento — forma alvo

O Codex deve produzir comandos idempotentes equivalentes a:

```text
make doctor
make bootstrap
make build-hosted
make test
make run-hosted
make build-native
make run-native-qemu
make package
```

`make doctor` é somente leitura e informa:

- capacidades presentes;
- dependências ausentes;
- modelos disponíveis;
- espaço necessário;
- recursos habilitados;
- comandos exatos de instalação para o host detectado.

Nunca instalar pacotes do sistema, drivers ou modelos pesados sem ação explícita do usuário.

## 11. Perfis de features

```text
casulo-minimal
  kernel/runtime T, memória, UI básica, sem modelos

casulo-voice
  ASR/TTS local

casulo-guide
  modelo local + embeddings + Guide

casulo-creator
  Forge + simulação + renderer

casulo-full
  todas as capacidades suportadas na máquina

legacy-research
  ferramentas históricas isoladas, nunca default
```

## 12. Requirements do usuário final

O instalador deve:

1. detectar hardware;
2. explicar capacidade em linguagem comum;
3. oferecer pacote de modelo compatível;
4. informar tamanho e tempo estimado;
5. pedir consentimento para download;
6. verificar hash/licença;
7. calibrar voz e tempo de resposta;
8. criar memória criptografada;
9. iniciar primeiro encontro com o Guia.

Sem cadastro obrigatório.

