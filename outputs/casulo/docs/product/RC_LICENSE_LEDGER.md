# Ledger de licenças — Revolution Closure

Este ledger é evidência de engenharia, não parecer jurídico. Redistribuição
comercial exige revisão separada de código, pesos, tokenizer, voz, G2P e notices.

| Componente | Licença/proveniência declarada | Perfil | Decisão RC0 |
|---|---|---|---|
| Casulo owner/core | propriedade de Guilherme Moura Fernandes | owner privado | permitido |
| Qwen3-4B GGUF | Apache-2.0 | bootstrap local, não embutido | adotado/verificado |
| llama.cpp b10362 | MIT | runtime local, não identidade do motor | adotado/verificado |
| whisper.cpp v1.9.2 | MIT | ASR hosted | adotado/verificado |
| Microsoft Maria/SAPI | componente do Windows; não redistribuído | fallback local | permitido apenas no host |
| Rust bootloader 0.11.15 | conforme lock/upstream; notices ainda requeridos | Native | uso de desenvolvimento |
| QEMU | GPL-2.0-or-later upstream | ferramenta externa do host | não distribuído no cliente |
| LLVM/Clang | Apache-2.0 WITH LLVM-exception upstream | ferramenta do host | não distribuído no cliente |
| Piper ativo | GPL-3.0 | candidato TTS | não adotado |
| sherpa-onnx + eSpeak NG | cadeia mista, inclui GPL-3.0-or-later | candidato TTS | `LICENSE_REVIEW_REQUIRED_NOT_ADOPTED` |
| QDK/Q# | não instalado; R&D apenas | nenhum | fora do caminho |

O inventário completo de pacotes Python e os hashes dos locks estão em
`docs/product/RC_DEPENDENCY_INVENTORY.json`. Metadado de licença ausente em um
pacote global não o promove a dependência Casulo; somente componentes
explicitamente admitidos podem entrar em artifact/SBOM.

