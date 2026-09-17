# FONTES TÉCNICAS E LINHAGEM

Consultadas na preparação em 2026-08-14. A execução deve resolver e pinar
versões/commits atuais; URL não autoriza download ou adoção.

## Baseline Casulo fornecido

- pacotes locais `CASULO_PRODUCT_EXECUTION_PACKAGE_2026-08-11`;
- `CASULO_GENERATIVE_VM_HANDOFF_PACKAGE_2026-08-11`;
- `CASULO_SEMANTIC_MULTIVERSE_GOAL_2026-08-12`;
- evidência anexada `CASULO_EINSTEIN_ANALYSIS_20260813-010229.zip`;
- estados e hashes narrados pelo usuário, a confirmar no repositório real.

## Modelos e treino

- Qwen3 oficial: https://github.com/QwenLM/Qwen3
- llama.cpp: https://github.com/ggml-org/llama.cpp
- llama.cpp GBNF/JSON schema: https://github.com/ggml-org/llama.cpp/tree/master/grammars
- PEFT LoRA: https://huggingface.co/docs/peft/main/conceptual_guides/lora
- PEFT quantization: https://huggingface.co/docs/peft/main/developer_guides/quantization
- TRL SFT: https://huggingface.co/docs/trl/en/sft_trainer
- TRL DPO: https://huggingface.co/docs/trl/en/dpo_trainer

## Voz

- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- WebRTC AEC3: https://webrtc.googlesource.com/src/+/main/modules/audio_processing/aec3/
- SpeexDSP: https://github.com/xiph/speexdsp
- ONNX Runtime Windows: https://onnxruntime.ai/docs/get-started/with-windows.html
- Kokoro-82M: https://huggingface.co/hexgrad/Kokoro-82M
- eSpeak NG: https://github.com/espeak-ng/espeak-ng
- Piper: https://github.com/OHF-Voice/piper1-gpl

## VM

- QEMU system: https://www.qemu.org/docs/master/system/
- QEMU WHPX: https://www.qemu.org/docs/master/system/whpx.html
- VirtIO: https://www.qemu.org/docs/master/system/devices/virtio/index.html
- UEFI 2.10: https://uefi.org/specs/UEFI/2.10/

## Nota de licença

Esta matriz é orientação de engenharia, não parecer jurídico. Runtime, código,
pesos, tokenizer, voz, dataset, phonemizer e notices devem ser auditados
separadamente antes de redistribuição comercial.

