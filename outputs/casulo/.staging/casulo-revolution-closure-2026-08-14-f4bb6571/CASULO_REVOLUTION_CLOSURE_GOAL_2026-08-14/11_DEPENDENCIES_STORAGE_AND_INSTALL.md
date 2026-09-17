# DEPENDÊNCIAS, ARMAZENAMENTO E INSTALAÇÃO

## 1. Regra zero

Este pacote **não autoriza instalação ou download silencioso**. O repositório e
seus locks são a fonte de verdade. Antes de qualquer mudança, produzir:

```text
docs/product/RC_MACHINE_PROFILE.json
docs/product/RC_DEPENDENCY_INVENTORY.json
docs/product/RC_INSTALL_PLAN.md
docs/product/RC_DISK_BUDGET.json
docs/product/RC_LICENSE_LEDGER.md
```

Cada item:

```text
name, purpose, current_version, target_version, source,
license, already_present, required_or_conditional,
download_bytes, installed_bytes, peak_temp_bytes,
hash, runtime_or_build_only, redistributable,
consent_required, rollback_cleanup
```

Reutilizar por content hash. Não reinstalar para “normalizar”.

## 2. Baseline a confirmar

- Windows 10/11 host e PowerShell;
- Python 3.13 do produto, se pinado/compatível;
- pytest e ferramentas existentes;
- Rust/Cargo;
- LLVM/Clang/LLD;
- CMake/Ninja;
- MSVC Build Tools e/ou MinGW conforme receipts atuais;
- QEMU x86-64, `qemu-img`, WHPX e OVMF;
- toolchain T/T Forge/TCAP;
- `llama.cpp b10362` e Qwen3-4B Q4_K_M;
- `whisper.cpp`, `base-q5_1`, `small-q5_1` e bridge ASR;
- DPAPI/Ed25519/SBOM/hash tooling já adotados;
- aproximadamente 82.46 GiB livres no último relato.

## 3. Required para o Goal

| Trilha | Dependência | Política |
|---|---|---|
| produto | locks Python/Rust/T existentes | reutilizar |
| neural | Qwen3-4B GGUF + llama.cpp | congelar hashes |
| schema | JSON Schema/GBNF support existente | pin runtime |
| VM | QEMU/WHPX/OVMF/QCOW2 | base read-only |
| ASR | whisper.cpp + modelos atuais | nenhum modelo novo inicialmente |
| build | LLVM/CMake/Ninja/MSVC/MinGW | apenas o já exigido |
| storage | store/SQLite ou mecanismo já adotado | sem DB novo por conveniência |
| security | hash/SBOM/signing/scanners first-party | ampliar testes |
| launcher | runtime nativo já adotado | sem instalador pesado por estética |

## 4. Treino isolado — condicional

Não usar Python 3.13 global implicitamente. Criar ambiente versionado, em geral
Python 3.11 ou 3.12 conforme wheels confirmados:

- PyTorch apropriado ao CPU/GPU;
- `transformers`;
- `datasets`;
- `peft`;
- `trl` apenas se SFT/DPO realmente usados;
- `accelerate`;
- `safetensors`;
- `numpy`, `scipy`, `pyarrow` conforme locks;
- `bitsandbytes` somente em hardware/OS suportado;
- scripts de conversão do mesmo commit de `llama.cpp`;
- `jiwer`, `soundfile` para evals de voz, se necessários.

O primeiro treino deve ser router/classificador first-party ou LoRA de modelo
pequeno. Checkpoint HF 4B, CUDA e QLoRA não são required para a prova humana na
máquina recebida.

## 5. Voz — candidatos condicionais

### AEC

- WebRTC Audio Processing/AEC3: preferido se integração/licença/NOTICE passarem;
- SpeexDSP BSD: fallback auditável;
- bindings comunitários só após provenance e manutenção avaliadas.

### TTS

- backend Windows atual para owner;
- Kokoro/ONNX como laboratório somente após cadeia de G2P/voz/licença;
- Piper GPL como componente opcional separado apenas com decisão explícita de
  compliance;
- G2P pt-BR first-party em T é caminho possível, não tarefa cosmética.

Não permitir que uma dependência GPL/voice-data restritiva vaze para
`casulo-public` ou seja chamada de permissiva.

## 6. Dependências evitadas por padrão

- Docker/WSL apenas para conveniência;
- Kubernetes, Redis, observability server;
- database server externo;
- framework de agentes de terceiros;
- API comercial de IA;
- cloud training/storage;
- múltiplos modelos 4B residentes;
- CUDA/ROCm sem hardware útil;
- Q#/QDK/QPU;
- FFmpeg no artifact sem auditoria específica;
- ANN externo antes de provar necessidade.

## 7. Orçamento de disco

O doctor calcula valores reais. Envelope inicial incremental:

| Item | Faixa planejada |
|---|---:|
| código/build intermediário | 3–8 GiB |
| overlay/snapshots esparsos | 8–20 GiB |
| laboratório pequeno de treino | 6–16 GiB |
| voz/AEC/TTS assets | 1–4 GiB |
| clean-test/materialization staging | 4–10 GiB |
| evidências/pacotes | 2–5 GiB |
| **pico incremental possível** | **24–63 GiB** |

Com ~82.46 GiB livres, o Goal é plausível **somente com reuse, staging limitado
e limpeza task-owned**. Regra:

```text
projected_free_after_peak >= 25 GiB
```

Se não passar:

- reduzir snapshots/checkpoints dentro do escopo do Goal;
- reutilizar blobs por hash;
- limpar somente staging/caches criados e manifestados pelo Goal;
- pedir direção antes de remover qualquer conteúdo preexistente;
- checkpointar em `BLOCKED_DISK_BUDGET`.

## 8. Treino 4B e disco

LoRA/QLoRA 4B adiciona checkpoint HF, ambiente GPU, optimizer/checkpoints,
conversão e quantização. Gate recomendado:

```text
free_space_before_4B_lab >= 120 GiB
```

160 GiB é margem mais confortável para várias tentativas. Os ~82 GiB atuais
não devem ser consumidos tentando acomodar isso à força. Treino completo ou
distilação pode exigir centenas de GiB e compute separado.

## 9. RAM/VRAM

```text
Inference Qwen3-4B Q4       = já validada no perfil recebido
Router/classifier training  = CPU/16 GiB plausível
Qwen3-0.6B LoRA smoke       = possível, lento, medir antes
Qwen3-4B QLoRA              = não gatear na GTX 1050 Ti 4 GiB
Recommended 4B QLoRA        = NVIDIA >=16 GiB VRAM; 24 GiB preferível
```

Jobs devem reservar núcleos/tempo para áudio e SO. O doctor estima, não promete.

## 10. Consentimento

Pedir consentimento literal antes de:

- download individual >250 MiB;
- conjunto de downloads >1 GiB;
- instalação global/admin;
- acesso físico a microfone/playback;
- compute externo;
- uso de sessão owner para treino;
- adoção de licença copyleft com impacto distributivo.

Antes de bloquear, continuar todo trabalho documental, código e teste seguro que
não dependa da ação.

## 11. Instalação e rollback

- venvs/build dirs task-owned;
- versões/commits/hashes pinados;
- downloads em staging com verificação antes de publish;
- model cards/licenses preservados;
- nenhum script remoto executado por pipe;
- sem alterar `PATH` global quando path explícito basta;
- cleanup lista apenas paths criados pelo Goal;
- uninstall/rollback documentado;
- SBOMs separados owner/public/cloud e treino/build.

## 12. Espaço externo futuro

O gate de dispositivo externo continua outra fase:

```text
external_usable_capacity_gib > 80
```

Os 80+ GiB livres no disco interno não autorizam formatar/gravar USB. Este Goal
termina na VM e na prova humana.

