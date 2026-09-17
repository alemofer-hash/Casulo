# Casulo OS — coexistência UEFI não destrutiva

Data do baseline: 2026-08-22

## Resultado implementado

O caminho padrão de instalação do Casulo OS não é mais a gravação crua de uma
imagem sobre um dispositivo inteiro. O produto dispõe de um bundle UEFI
content-addressed e de um instalador transacional que adiciona arquivos novos a
uma partição EFI montada, recusa colisões e nunca formata, reparticiona, apaga ou
sobrescreve arquivos preexistentes.

Isso permite coexistência com outros sistemas já presentes no mesmo pendrive ou
HD. A compatibilidade foi exercitada em árvores ESP sintéticas representando
Windows Boot Manager, GRUB, systemd-boot e rEFInd. Em todos os casos, cada byte
preexistente permaneceu idêntico e o rollback retornou a árvore ao hash exato
anterior.

Esse resultado é uma validação de software. Nenhum disco físico foi escrito
neste gate.

## Artefatos

- imagem UEFI autônoma NP11:
  `release/casulo-native-neural-port-np11.img`;
- SHA-256 da imagem:
  `1efca6e5caccc68a65c51309abc9f6bef63b401a48a1a30fc569974c778c94a9`;
- bundle coexistente:
  `release/CASULO_UEFI_COEXISTENCE_BUNDLE_2026-08-22`;
- SHA-256 do manifest do bundle:
  `e184ae82e0619c32adc3af5017410f9891c4076e9e71f3e5772591806044ba63`;
- system pack físico:
  `release/casulo-native-physical-creation-system-pack-v1.cspk`;
- SHA-256 do system pack:
  `d233d0c5c23d0cf6e0a638fa8ce756eee076fd717d8dbd16f7293f278bbb1b61`.

O system pack contém o modelo owner Qwen3-4B Q4_K_M de 2.497.280.256 bytes,
SHA-256
`7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`,
como entrada validada do ramdisk. O kernel consome a entrada diretamente; não
depende de `fw_cfg`, filesystem do host, rede ou API externa.

## Layout do bundle

```text
EFI/Teloscorp/Casulo/CasuloX64.efi
kernel-x86_64
ramdisk
```

O executável fica no namespace próprio `EFI/Teloscorp/Casulo`. Os dois arquivos
na raiz são exigidos pela ABI do bootloader rust-osdev adotado. Por isso, o
instalador recusa a operação caso `kernel-x86_64` ou `ramdisk` já existam, mesmo
que tenham nomes de outro produto. Ele não renomeia nem substitui arquivos.

Uma futura ABI de boot própria deverá mover os três itens ao namespace Casulo;
isso elimina as duas reservas na raiz, mas não é requisito para a coexistência
segura atual.

## Protocolo transacional

1. `inspect` percorre somente arquivos regulares, recusa symlinks e calcula o
   hash canônico da árvore EFI.
2. `plan` compara caminhos sem distinguir maiúsculas de minúsculas, lista toda
   colisão e congela o hash anterior.
3. `apply` exige opt-in de ESP montada e uma frase que contém os 16 primeiros
   dígitos do hash congelado.
4. Antes de copiar, a árvore é inspecionada novamente. Qualquer mudança depois
   do plano aborta a transação.
5. EFI, kernel, ramdisk e drop-ins são copiados e verificados integralmente em
   staging. Somente depois todos são promovidos por renames no mesmo filesystem;
   uma exceção de I/O recuperável não expõe um destino parcial.
6. O receipt enumera exatamente o que foi criado. Não há lista de overwrites ou
   deletes porque essas operações são proibidas.
7. `rollback` exige a frase específica da transação e remove somente arquivos
   cujo hash ainda corresponde ao receipt. Um arquivo alterado depois da
   instalação impede o rollback automático.

O módulo não contém código para `PhysicalDrive`, `diskpart`, `Clear-Disk`,
`Format-Volume` ou escrita da rota de fallback `EFI/BOOT/BOOTX64.EFI`.

## Integração com boot managers

| Ambiente encontrado | Integração nova | Condição | Estado honesto |
| --- | --- | --- | --- |
| systemd-boot | `loader/entries/casulo.conf` | entrada ainda não existe | selecionável pelo menu |
| GRUB | `grub/custom.cfg` | um `grub.cfg` UTF-8 e limitado contém `source` ou `configfile` para `custom.cfg` | selecionável pelo menu |
| GRUB sem consumo comprovado de `custom.cfg` | nenhuma alteração de configuração existente | não se presume comportamento | requer entrada UEFI/manual posterior |
| rEFInd | namespace vendor | descoberta automática pode ser usada | depende das políticas de scan locais |
| somente Windows Boot Manager | namespace vendor | nenhum BCD é alterado | requer entrada de firmware UEFI posterior |

O instalador nunca modifica `grub.cfg`, `refind.conf`, `loader.conf`, BCD ou
variáveis NVRAM. A etapa de registro no firmware será outro adaptador,
separadamente auditado e reversível. Até ele existir, `UEFI_FIRMWARE_ENTRY_REQUIRED`
é um resultado válido, não uma falha silenciosa.

## Evidência executada

O boot NP11 em QEMU/WHPX foi executado a partir da própria imagem UEFI, sem
`fw_cfg` e com a imagem read-only. O kernel validou nove entradas do system
pack, carregou 2.497.280.256 bytes do modelo a partir do ramdisk, produziu 34
tokens, compilou o T gerado, simulou, julgou e materializou o artefato. Marcadores
principais:

```text
CASULO_NATIVE_SYSTEM_PACK_ENTRIES=9
CASULO_NATIVE_SYSTEM_PACK_FULL_MODEL=PRESENT_VALIDATED
CASULO_NATIVE_CREATION_MODEL_TRANSPORT=uefi-ramdisk-content-addressed/1.0
CASULO_NATIVE_CREATION_OUTPUT_TOKENS=34
CASULO_NATIVE_CREATION_SPEC=PASS
CASULO_NATIVE_CREATION_SIMULATION=PASS
CASULO_NATIVE_CREATION_ACCEPTANCE=PASS
CASULO_NATIVE_CREATION_GATE=PASS
CASULO_NATIVE_NEURAL_INFERENCE=BOOT_TO_CREATION_T_AUTHORIZED
```

Evidência autoritativa:
`outputs/casulo/native-multiboot/2026-08-22-np11-ramdisk-qemu-attempt-2.json`.
A tentativa anterior que terminou no token 26 por timeout permanece preservada
como evidência parcial, não como PASS.

A matriz final de coexistência está em
`outputs/casulo/native-multiboot/2026-08-22-coexistence-validation-attempt-4`.
Uma perda abrupta de energia durante a curta sequência de publicação ainda pode
exigir recuperação pelo inventário; ela não autoriza sobrescrita de arquivos
preexistentes.

## Fronteira física atual

No inventário read-only final, o Windows expôs somente o NVMe interno de boot.
Nenhum pendrive elegível estava visível ao subsistema de armazenamento. Portanto:

- o software de coexistência está implementado e validado;
- a imagem autônoma está validada em UEFI virtual;
- o pendrive do usuário não foi modificado;
- o Casulo ainda não deve ser anunciado como opção presente no menu físico;
- a próxima operação física começa por identificar e montar a ESP correta,
  executar `inspect` e revisar o plano; nunca por gravar a imagem crua.

## Claims permitidos

Permitido: “O Casulo possui um instalador UEFI coexistente, transacional e
fail-closed, validado contra árvores representativas de Windows, GRUB,
systemd-boot e rEFInd, sem sobrescrever sistemas existentes.”

Não permitido ainda: “funciona em qualquer firmware”, “já está instalado no
pendrive atual”, “Secure Boot aprovado”, “persistência em mídia física provada”
ou “boot físico aprovado”.
