# GOAL — Casulo Native First Conversation

Data de abertura: 2026-08-20  
Estado: `BLOCKED_NATIVE_INFERENCE_ABI`  
Proprietário: Guilherme Moura Fernandes / Teloscorp

## Missão

Transformar a Native Foundation na primeira experiência owner utilizável sem
Windows, Linux, VM, API externa ou serviço hospedado depois do boot. O primeiro
alvo é text-first e deve executar em QEMU antes de qualquer mídia física:

```text
UEFI
-> kernel Casulo
-> projeção Stark + Jobs
-> entrada local
-> inferência neural local em ring 3
-> stream de tokens
-> programa T
-> TCAP
-> execução isolada
-> persistência no dispositivo Casulo
```

UEFI, Rust/LLVM, Qwen e primitives de `llama.cpp` permanecem dependências
declaradas. Nenhuma delas pode esconder Windows, Linux, Python, processo host
ou bridge serial no caminho bare-metal final.

## Fronteira atual confirmada

A Native Foundation já possui boot UEFI, memória, framebuffer básico, timer,
serial, ramdisk, ring 3, syscalls, TCAP e o contrato de eventos do produto. Ela
não possui hoje inferência neural, renderer principal, input físico geral,
memória persistente, áudio ou materialização nativos.

A imagem histórica `release/casulo-native-x86_64.img` permanece preservada e
não será chamada de sistema utilizável.

## Sequência vinculante

1. `NF0`: freeze, inventário e hardware profile.
2. `NF1`: `ProductEvent -> SceneState -> PresentationProjector` bounded em
   `no_std`, com replay equivalente ao Hosted.
3. `NF2`: renderer GOP, texto, foco e input mínimo no QEMU.
4. `NF3`: ABI ring 3 mínima para uma primitive neural.
5. `NF4`: primeiro token Qwen real sem host; fixture/replay/fake valem zero.
6. `NF5`: Guide Presence, geração T e execução TCAP mínima.
7. `NF6`: system pack selado e estado append-only.
8. `NF7`: três boots e USB virtual em QEMU.
9. `NF8`: imagem owner-alpha, manifest, SBOM, hashes e assinatura de
   desenvolvimento.
10. `NF9`: seleção física explícita e readback do pendrive.
11. `NF10`: prova humana de boot, conversa, criação e retomada.

## Gates inegociáveis

- o modelo precisa gerar tokens novos dentro do ambiente Native;
- nenhum stdout, processo Windows, Python, HTTP ou bridge host pode fornecer a
  resposta final;
- o renderer não possui autoridade e não fabrica progresso;
- toda conclusão de job exige receipt válido;
- modelo generativo nunca concede capability;
- dataset/modelo/system pack são verificados antes do consumo;
- nenhum disco interno é montado ou escrito;
- rede permanece ausente;
- Secure Boot, firmware, TPM e BitLocker não são alterados automaticamente;
- flash físico requer identidade completa do dispositivo e confirmação humana
  destrutiva específica.

## Estados terminais

```text
CASULO_NATIVE_USB_OWNER_ALPHA_FIRST_USE_CONFIRMED
READY_FOR_EXPLICIT_USB_SELECTION
BLOCKED_NATIVE_INFERENCE_ABI
BLOCKED_TARGET_HARDWARE_DRIVER
BLOCKED_SECURE_BOOT
IN_PROGRESS_CHECKPOINTED
```

Até `NF4`, a formulação permitida é apenas: a fundação Native está sendo
preparada para hospedar o motor. Depois de `NF4`, pode-se afirmar que uma
primitive neural local executou sob o Casulo OS, dentro do escopo comprovado.

## Fechamento local de 2026-08-20

NF0–NF3 e NF5–NF8 possuem gates locais. NF4 não passou: o modelo Qwen foi
revalidado por hash, mas nenhum byte dele foi consumido pelo processo Native.
O runtime adotado é PE/COFF Windows e não existe no cache uma implementação
freestanding do loader/grafo Qwen. O evento de token NF3 prova o ABI e não
inferência.

A imagem owner-alpha foi selada somente como
`FLASHABLE_PREVIEW_NOT_CONVERSATIONAL`. O USB virtual passou três boots; nenhum
dispositivo físico foi escrito. NF9 encontrou somente o NVMe de sistema e o
recusou. NF10 permanece humano e posterior ao porte neural.
