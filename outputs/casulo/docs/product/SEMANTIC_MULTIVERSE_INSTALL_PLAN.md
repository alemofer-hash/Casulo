# Plano de instalação do Semantic Multiverse

Estado: `NO_INSTALL_REQUIRED_FOR_SM0_SM10_INITIAL_SLICE`

| Item | Classe | Presente | Download | Instalado incremental | Pico | Licença/origem | Rollback |
|---|---|---:|---:|---:|---:|---|---|
| Python/stdlib/pytest | required | sim | 0 | 0 | 0 | toolchain existente | nenhum |
| Rust nightly pinado | required Native | sim | 0 | 0 | 0 | rustup existente | nenhum |
| LLVM/Clang/LLD | required Native | sim | 0 | 0 | 0 | instalação existente | nenhum |
| QEMU/WHPX/OVMF | required VM | sim | 0 | 0 | overlay esparso até 10 GiB | instalação existente | remover apenas overlay deste Goal após revisão humana |
| Qwen3-4B Q4_K_M | required owner | sim | 0 | 0 | 0 | Qwen, Apache-2.0, hash congelado | não duplicar/não remover |
| llama.cpp b10362 | required owner | sim | 0 | 0 | 0 | ggml-org, MIT, hash congelado | não duplicar/não remover |
| índice lexical/hierárquico | required | implementação first-party | 0 | <100 MiB | <250 MiB | código owner | apagar somente staging identificado |
| content-addressed store | required | implementação first-party/stdlib | 0 | <500 MiB | <1 GiB | código owner | GC dry-run; sem delete automático |
| ANN externo | optional | não | 0 planejado | 0 | 0 | não adotado | n/a |
| Q#/QDK CLI | R&D only | somente extensão VS Code | 0 planejado | 0 | 0 | não adotado no runtime | n/a |
| tensor networks/solver | R&D only | não necessário | 0 planejado | 0 | 0 | não adotado | n/a |

Nenhum item ultrapassa o gate de consentimento de 250 MiB porque nenhum download
novo será feito. A extensão Q# existente não autoriza QPU, Azure, rede nem claim
quântico. Se uma lacuna futura exigir pacote pesado, este plano será congelado
novamente e o consentimento literal será solicitado antes do download.
