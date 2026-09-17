# Plano de instalação — Revolution Closure

Estado do RC0: nenhuma instalação ou download necessário.

## Required e já presente

| Componente | Uso | Origem/versão | Estado |
|---|---|---|---|
| Python | produto hosted e gates | 3.13.2 | presente |
| Rust nightly | Casulo Native | nightly-2026-02-01, lock existente | presente |
| QEMU/OVMF | VM owner | 11.0.50 | presente |
| LLVM/Clang | toolchain Native | 22.1.8 | presente |
| Qwen3-4B Q4_K_M | bootstrap neural local | revisão e hash congelados | presente |
| llama.cpp | runtime neural local | b10362 | presente |
| whisper.cpp base/small q5_1 | ASR hosted pt-BR | v1.9.2 | presente |

## Optional e não adotado

- TTS redistribuível: `LICENSE_DECISION_PENDING`; nenhuma engine/peso será
  baixado até haver decisão de licença e consentimento material.
- QLoRA/adapter 4B: `DEFERRED_COMPUTE_NOT_AVAILABLE`; requer checkpoint
  treinável, GPU e no mínimo 120 GiB livres, inexistentes neste Machine Profile.
- Q#/QDK, ANN externo e solvers: `R_AND_D_ONLY_NOT_REQUIRED`; fora do caminho
  owner e incapazes de conferir capacidade quântica a este host.

## Plano por sprint

1. RC1–RC4: biblioteca padrão e toolchains atuais; download previsto `0`.
2. RC5: treinar somente um router/classifier pequeno first-party com o ambiente
   atual; não treinar o GGUF e não adicionar stack pesada.
3. RC6–RC7: reutilizar QEMU, imagem e modelo existentes sem duplicar pesos/base.
4. RC8: primeiro integrar e medir as rotas de voz já adotadas; qualquer novo
   runtime/voz para redistribuição exige novo ledger, licença e consentimento.
5. RC9–RC13: builds e evidence em staging, com limpeza permitida apenas do
   staging criado por este Goal após selagem.

Pico local reservado para todo o Goal: 4 GiB. Espaço projetado após o pico:
73,92 GiB, acima da reserva vinculante de 25 GiB. Nenhuma mídia externa será
usada.

