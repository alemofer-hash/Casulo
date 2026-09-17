# NP11 + coexistência UEFI — selo de implementação

Estado: `NATIVE_UEFI_MULTIBOOT_COEXISTENCE_VALIDATED_PHYSICAL_INSTALL_PENDING`

## Resultado

- modelo completo transportado por ramdisk UEFI content-addressed: PASS;
- boot-to-creation sem QEMU `fw_cfg`: PASS;
- T gerado e compilado, simulação, julgamento e materialização: PASS;
- instalação por adição de arquivos, sem overwrite/delete: PASS;
- staging integral antes de publicação: PASS;
- rollback vinculado ao receipt e ao hash: PASS;
- Windows, GRUB comprovado, systemd-boot e rEFInd sintéticos: PASS;
- fallback `EFI/BOOT/BOOTX64.EFI` preservado: PASS;
- restauração exata da árvore anterior: PASS;
- regressão Python focal: 24/24 PASS;
- escrita em dispositivo físico: NÃO EXECUTADA;
- boot em hardware físico: NÃO VERIFICADO.

## Ativação por ambiente

- Windows-only: `UEFI_FIRMWARE_ENTRY_REQUIRED`;
- GRUB com `source/configfile custom.cfg` comprovado:
  `GRUB_VERIFIED_CUSTOM_CFG_DROP_IN`;
- systemd-boot: `SYSTEMD_BOOT_NEW_ENTRY`;
- rEFInd: `REFIND_AUTO_DISCOVERY`, sujeito à política local.

GRUB não comprovado é tratado como `UEFI_FIRMWARE_ENTRY_REQUIRED`. O produto
não altera configuração preexistente para forçar ativação.

## Hashes de produto

- NP11: `1efca6e5caccc68a65c51309abc9f6bef63b401a48a1a30fc569974c778c94a9`;
- system pack: `d233d0c5c23d0cf6e0a638fa8ce756eee076fd717d8dbd16f7293f278bbb1b61`;
- modelo: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- manifest do bundle: `e184ae82e0619c32adc3af5017410f9891c4076e9e71f3e5772591806044ba63`;
- evidência QEMU: `29e8a7753d8dc7f5363e1308b3427efddc7cc5e8d5509c6287368f5df7e10a6c`;
- relatório de coexistência: `8f9e3ae2554b73d265fb8d5fa91c0979845b66862168857fe3b4fa23449439f6`.

## Limites

O inventário final do Windows expôs apenas o NVMe interno; nenhum USB elegível
estava presente. Secure Boot, criação de entrada NVRAM, boot físico e
persistência física não foram aprovados. O próximo passo é montar a ESP do
dispositivo correto e executar somente `inspect` e `plan` antes de qualquer
confirmação de escrita.

