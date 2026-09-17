# Instalações obrigatórias

Este documento é a lista de capacidade. Versões exatas devem ser congeladas em `manifests/toolchain.lock.template.json` após o preflight e a instalação. Não instale duas ferramentas que cumpram a mesma função sem justificativa medida.

## Windows obrigatório

| Componente | Função | Forma preferida |
|---|---|---|
| Windows 11 x64 atualizado | host e rede | Windows Update deliberado antes do sprint |
| WinGet/App Installer | bootstrap verificável | componente oficial do Windows |
| PowerShell 7 | scripts | `Microsoft.PowerShell` |
| Git for Windows | versionamento | `Git.Git` |
| Git LFS | artefatos quando explicitamente necessário | `GitHub.GitLFS` |
| Visual Studio Build Tools 2022 + C++ | compilação nativa | workload VCTools |
| CMake | configuração de build | `Kitware.CMake` |
| Ninja | build | `Ninja-build.Ninja` |
| LLVM/Clang | análise/compilação | `LLVM.LLVM` |
| Rustup | toolchain Rust | `Rustlang.Rustup` |
| Python 3.11+ | tooling e legado | versão exigida pelo repositório |
| Node.js LTS | PWA/UI | versão exigida pelo lockfile |
| FFmpeg/FFprobe | áudio | build confiável registrado |
| mkcert | CA/TLS local durante o RP0.1 | `FiloSottile.mkcert` |
| Trivy | SBOM e auditoria offline | preservar 0.74.0 ou congelar substituto validado |
| WSL2 + Ubuntu 24.04 | host Linux | `wsl --install -d Ubuntu-24.04` |
| VS Code | edição/WSL | opcional operacional, recomendado |
| HWiNFO | telemetria térmica | preservar instalação existente |
| driver Intel atualizado | Vulkan/OpenVINO | OEM/Intel, não instalador aleatório |

## Ubuntu 24.04/WSL obrigatório

```text
build-essential git git-lfs curl ca-certificates
cmake ninja-build pkg-config clang lld llvm
gdb lldb python3 python3-venv python3-pip
sqlite3 libsqlite3-dev ffmpeg jq ripgrep fd-find
qemu-system-x86 ovmf mtools dosfstools
openssl libssl-dev
```

Rust deve ser instalado por `rustup` e pinado pelo repositório. Node deve seguir o lockfile/projeto; não instalar dependências globais desnecessárias.

## Runtime de IA obrigatório

- `llama.cpp`/`llama-server`, compilação ou binário congelado por commit/hash;
- um modelo GGUF geral/código 7–9B em Q4 aproximado;
- `whisper.cpp` e os pesos já validados pelo Casulo;
- TTS Maria e bridge existente, se a auditoria confirmar integridade;
- um embedder multilíngue pequeno;
- licenças e SHA-256 de cada peso/binário.

## Segurança e diagnóstico obrigatórios

- firewall do Windows;
- TLS local;
- ferramenta de varredura de segredos ou heurística local documentada;
- Trivy 0.74.0 congelado, se o binário anterior estiver íntegro;
- SBOM por release;
- `netstat`/`Get-NetTCPConnection` para provar bindings;
- utilitários de hash SHA-256;
- backup Git bundle em outro dispositivo.

## Deliberadamente não obrigatórios

- Docker Desktop;
- Kubernetes;
- Redis/PostgreSQL;
- banco vetorial remoto;
- Ollama como camada obrigatória;
- CUDA;
- eGPU;
- conta Hugging Face após o download;
- serviços de túnel ou VPN de terceiros;
- API paga.

## Fontes oficiais

- WSL: https://learn.microsoft.com/windows/wsl/install
- Rede WSL: https://learn.microsoft.com/windows/wsl/networking
- WinGet: https://learn.microsoft.com/windows/package-manager/winget/install
- llama.cpp: https://github.com/ggml-org/llama.cpp
- servidor llama.cpp: https://github.com/ggml-org/llama.cpp/tree/master/tools/server
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- Rustup: https://rustup.rs/
