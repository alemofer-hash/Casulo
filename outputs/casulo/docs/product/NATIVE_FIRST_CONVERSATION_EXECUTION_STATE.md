# Estado — Casulo Native First Conversation

## Checkpoint NF0 — 2026-08-20

- estado: `NF0_BASELINE_FROZEN`;
- branch: `product/semantic-multiverse`;
- commit-base: `df12e916c90d9bd2b966326275dc191573f38abd`;
- worktree histórico: `293` entradas (`22` modificadas, `271` não rastreadas,
  zero remoções); nenhuma foi apagada, movida ou reclassificada;
- espaço livre no volume C: `67.456.155.648` bytes (`62,82 GiB`);
- imagem Native histórica: `2.162.688` bytes, SHA-256
  `ec4141c497d99e6ef70b93fd3048053b5a4c1a4911dd86f7b2450bb0fdf51e2d`;
- contrato UX: SHA-256
  `4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9`;
- scene contract: SHA-256
  `804ceb12b510f250cfd41a6e49185fe8db73f13c09a7f3288703368889435a8d`;
- modelo Qwen3-4B Q4_K_M: `2.497.280.256` bytes, SHA-256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- QEMU: `11.0.50`, executável local SHA-256
  `b396eb9b669f6282ec60f0d46e6addca8c669992e67a34365be44cd3cb97c9a7`;
- toolchain: Rust/Cargo `1.93.0`, target host GNU; kernel usa o target
  `x86_64-unknown-none`;
- nenhum download, instalação, benchmark ou acesso de rede iniciado;
- nenhum USB, block device, firmware ou configuração de boot tocado.

## Hardware alvo observado

- Lenovo `82VY`;
- Intel Core i5-1235U, 10 cores/12 threads;
- RAM física: `16.890.978.304` bytes;
- Intel Iris Xe;
- BIOS Lenovo `JKCN47WW` de 2024-08-20;
- teclado reportado por ACPI como `IDEA0103`;
- controladores Intel USB 3.20 `VEN_8086&DEV_461E` e USB 3.10
  `VEN_8086&DEV_51ED`;
- estado de Secure Boot: `UNKNOWN_ACCESS_DENIED`; não será inferido como off;
- virtualização de firmware reportada como desativada; QEMU TCG permanece
  disponível e é suficiente para os gates locais.

## Riscos dominantes

1. `NATIVE_INFERENCE_ABI`: o runtime adotado é binário Windows e não pode ser
   reutilizado no kernel; será necessário compilar uma primitive freestanding
   ou portar uma superfície estreita para o ABI Casulo.
2. `MODEL_MEMORY`: carregar o GGUF como ramdisk consome cerca de 2,33 GiB antes
   das estruturas de inferência; cabe em 16 GiB, mas exige contabilidade e
   limites antes do boot físico.
3. `INPUT_TARGET`: o teclado ACPI não prova compatibilidade i8042; QEMU será
   implementado antes de escolher driver físico.
4. `USB_XHCI`: persistir no próprio pendrive exigirá driver/storage delimitado
   ou uma fase UEFI de carga mais uma partição de estado suportada.
5. `SECURE_BOOT`: status ainda desconhecido; nenhuma mudança automática será
   feita.

## NF1–NF3 — apresentação e ABI

- `presentation-core` `no_std`: replay Hosted/Native, scene state fixo,
  renderer GOP, decoder Set 1 e journal; `9/9` testes Rust;
- contrato comum também passou `7/7` testes Node, `6/6` Tauri e regressões
  Python;
- primeiro NF2 falhou com `DOUBLE_FAULT`; a causa foi orçamento de pilha do
  renderer transacional. Tentativa preservada, stack explicitada e regressão
  de tamanho adicionada;
- NF2 final: imagem SHA-256
  `209ac850e4498137dcd8342473b8d6b662704371995dfe99f923f486ac6752c0`;
- NF3: processo ring 3 consumiu capabilities `MODEL_ASSERT`, `DOT_I16X4` e
  `TOKEN_EMIT`; probe sem capability observou `EPERM` e zero primitive;
- imagem NF3 SHA-256
  `a7d46391827209753b24d5b63f1aa278a996b1c80458ccb3b8aac031d8f752bd`;
- o token `42` é evento sintético do ABI. `MODEL_BYTES=0` e
  `NEURAL_INFERENCE=NOT_EXECUTED` são invariantes do gate.

## NF4 — bloqueio causal

Estado: `BLOCKED_NATIVE_INFERENCE_ABI`.

O doctor leu o cache owner real e confirmou:

- Qwen3-4B Q4_K_M: `2.497.280.256` bytes; SHA-256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- `llama-server.exe`: `PE_COFF_WINDOWS`;
- source llama.cpp/ggml freestanding no cache: zero;
- QEMU: `256M`; heap kernel: `2 MiB`;
- loader GGUF, Q4_K, RMSNorm, RoPE, atenção, FFN, KV, tokenizer e sampler
  Native: ausentes.

Evidência: `outputs/casulo/native-first-conversation/2026-08-20-nf4/native-inference-blocker.json`.

## NF5–NF6 — system pack e journal

- system pack determinístico: `14.530` bytes, SHA-256
  `9af383a88b06d4365cbf526e55243cad4ff0b8e1ba173e3869d28a35ee9c344a`;
- entradas: TCAP real, contrato UX e source T do Guia; todas verificadas;
- TCAP executado; source T do Guia `PRESENT_NOT_EXECUTED`;
- journal SHA-256 encadeado passou replay/corrupção;
- `MEDIA_WRITES=0`; persistência após reboot continua `NOT_PROVEN`;
- imagem NF6 SHA-256
  `dc6bd6ef3153d9a8ec832913918648b6c1443826537b341a35dd53f7c176d060`.

## NF7–NF9 — mídia virtual, bundle e preflight físico

- USB virtual `qemu-xhci/usb-storage`: `3/3` boots PASS, read-only, sem rede;
- hash antes/depois idêntico:
  `dc6bd6ef3153d9a8ec832913918648b6c1443826537b341a35dd53f7c176d060`;
- NF8 interativo: QEMU permaneceu vivo após todos os gates; SHA-256
  `667e7a1db08a7fb034cc62ad5f35373c0cf5f3f790b66e8a7fed09663e0f7d11`;
- bundle final: `release/CASULO_NATIVE_OWNER_ALPHA_PREVIEW_2026-08-20-attempt-4`;
- manifest SHA-256:
  `6ad4790479d443f88ed1814bb113e8aaa9d99d8d38e2740ee4bc67114b8b6114`;
- assinatura Ed25519 verificada e rotulada
  `DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE`;
- a prova NF8 executou `3/3` boots do próprio hash interativo, encerrados pelo
  runner somente depois do marcador de prontidão;
- doctor final do bundle: `14/14` checks PASS; recibo append-only em
  `outputs/casulo/native-first-conversation/2026-08-20-nf8/owner-alpha-doctor-final-check.json`;
- attempts 1–3 permanecem históricos/superseded; o attempt 3 ainda apontava a
  evidência de boots NF7 e não é o handoff corrente;
- preflight de discos: somente NVMe interno boot/system, recusado; estado
  `NO_ELIGIBLE_USB_PRESENT`; zero write.

## Regressão focal final

- Python: `18 passed`;
- Rust `presentation-core`: `9 passed`;
- Node: `7 passed`;
- Tauri Rust: `6 passed`;
- kernel/image: release build offline/locked PASS;
- QEMU USB virtual: `3/3 PASS`;
- QEMU preview interativo: `3/3 PASS`; o runner incremental encerrou cada QEMU
  somente depois do marcador final de prontidão, sem depender de timeout como
  resultado do gate;
- nenhuma campanha científica, benchmark, rede, Cloud ou escrita física.

## Estado e próximo passo exato

Resultado local do Goal: preview Native selado e gate físico preparado. A
conversa neural permanece em `BLOCKED_NATIVE_INFERENCE_ABI`.

Espaço livre na verificação final: `66.142.720.000` bytes (`61,60 GiB`).

Próximo trabalho é um Goal próprio de porte neural: adotar/implementar uma
primitive GGUF/Qwen freestanding auditada, mapear pesos read-only com orçamento
de memória, implementar tokenizer/grafo/KV/sampler e exigir o primeiro token
derivado dos pesos dentro do QEMU. Somente depois disso selecionar um USB e
pedir confirmação destrutiva específica. NF10 continua pertencendo a Guilherme.
