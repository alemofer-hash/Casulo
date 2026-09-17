# Hosted versus Native no Product Alpha

| Capacidade | Hosted Alpha | Native Foundation |
|---|---|---|
| voz fisica pt-BR | Windows, local | pendente |
| TTS/barge-in | Windows hosted | pendente |
| Guide Presence | first-party + modelo local | event loop e contrato prioritário; inferência permanece hosted |
| memoria | append-only + DPAPI | pendente |
| Creation Field | HTML/SVG hosted | framebuffer de boot apenas |
| T/TCAP | pipeline geral | loader/execucao ring 3 |
| capabilities | broker deny-by-default | mask/syscall deny |
| simulacao | completa sem efeitos | nao portada |
| materializacao | pacote/API local | nao portada |
| rede | opcional/explicita | desativada no gate |
| UX events | `casulo.owner-ux-event/1.0` | mesmo contrato, validador bounded e boot QEMU PASS |

O Hosted Product Profile continua sendo o produto utilizável. Native comprova
boot, HAL inicial, isolamento, execução TCAP e o plano de controle de presença,
streaming e jobs; não bloqueia o Alpha por ausência de drivers próprios de
áudio/GPU/rede nem finge que inferência neural já foi portada.
