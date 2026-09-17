# Casulo Native Foundation

O perfil Native atual e uma fundacao x86-64 `no_std` em Rust, iniciada por UEFI.
Ele nao e apresentado como substituto do Hosted Profile nem possui drivers
proprios completos de audio, GPU ou rede.

## Contratos comprovados

- imagem regular reproduzivel; nenhuma escrita automatica em dispositivo;
- QEMU `q35`, TCG, dois vCPUs, rede desabilitada e disco read-only;
- framebuffer e serial;
- memoria fisica UEFI, paging, heap, GDT/IDT, timer e watchdog;
- processo ring 3 com CR3 separado e paginas RX/NX;
- syscall/sysret, IPC, yield, fault containment e preempcao limitada;
- loader TCAP fail-closed com hash, limites, permissions e quarentena;
- execucao de um artefato T/TCAP isolado;
- contrato UX Hosted/Native selado, fila bounded com `PRESENCE` prioritária,
  stream ordenado e lifecycle de jobs/cancelamento fail-closed;
- shutdown seguro por dispositivo virtual de debug.

## Gate de produto

`os/tools/run_product_alpha_qemu.py` seleciona apenas marcadores de correcao do
produto. Loss, energia, wall time e speedup nao fazem parte do gate. O canario
historico continua preservado como payload de correcao; ele nao e apresentado
como unidade cientifica completa.

Capacidades que permanecem hosted: áudio físico, ASR/TTS, renderer principal,
memória DPAPI, modelo local do Guia e materialização para processos do host. O
gate ARC-10 prova o plano de controle Native; não reclassifica esses adapters
como drivers do SO.
