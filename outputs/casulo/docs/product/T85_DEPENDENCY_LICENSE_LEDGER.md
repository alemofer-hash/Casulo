# T85 dependency and license ledger

Este ledger é técnico, não parecer jurídico. Versões e hashes pertencem ao
Machine Profile e aos registries selados; redistribuição comercial exige revisão
profissional e notices finais.

| Componente | Papel | Versão/identidade | Licença registrada | Empacotado no T85 | Fronteira |
|---|---|---|---|---|---|
| Casulo owner e T runtime | decisão/orquestração first-party | T/2.0 + runtime Rust atual | proprietária Teloscorp | sim | owner privada |
| Qwen3-4B GGUF Q4_K_M | pesos bootstrap generativos | revisão `bc640142c66e…`; SHA `7485fe6f…` | Apache-2.0 | não; cache owner | primitive neural estrangeira |
| llama.cpp | inferência GGUF | b10362, commit `4801e3c567…`; archive `a9d95d26…` | MIT | não; cache owner | primitive C/C++ estrangeira |
| Python | hosted shell e launchers | 3.13.2 observado | PSF-2.0 | não | runtime do host |
| QEMU/OVMF | virtualização/boot | QEMU 11.0.50 observado | GPL-2.0-only / licença EDK II a revisar | não | ferramenta do host |
| Rust/Cargo | build do runtime T/Native | Rust 1.93.0; nightly native pinada | toolchain upstream | binário apenas | build tool |
| Whisper.cpp | ASR local | v1.9.2, commit `306c88f4…` | MIT | não; cache owner | primitive ASR estrangeira |
| Modelo Whisper base/small q5_1 | pesos ASR | hashes no voice registry | licença do modelo registrada nos cards | não; cache owner | pesos bootstrap |
| sounddevice/PortAudio | captura PCM | sounddevice 0.5.5 observado | MIT | não | dependência do host |
| Microsoft Maria/SAPI | TTS local do sistema | componente Windows | componente do sistema, não redistribuído | não | primitive de voz do host |
| psutil | observação física do working set | versão instalada no Machine Profile | BSD-3-Clause declarada pelo pacote | não | dependência do host |

Cloud permanece `RELEASE_LOCKED`; pacotes/credenciais de servidor não fazem
parte do release owner. QPU, USB e block devices não são dependências nem alvos.
