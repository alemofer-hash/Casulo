# Instalação coexistente do Casulo OS

Este runbook adiciona o Casulo a uma partição EFI montada sem formatar o disco,
sem substituir `EFI/BOOT/BOOTX64.EFI` e sem apagar outro sistema.

Não use `casulo-native-neural-port-np11.img` com gravadores de imagem em um
pendrive que contenha dados ou outros sistemas. A imagem inteira serve para VM e
mídia dedicada; o caminho de coexistência usa o bundle de arquivos.

## 1. Inspeção read-only

Substitua `X:\` pela raiz da partição EFI montada:

```powershell
python tools/casulo_multiboot.py inspect --efi-root "X:\"
```

Confirme visualmente o disco, o volume e os boot managers. O NVMe interno de
boot nunca deve ser escolhido como se fosse o pendrive.

## 2. Plano append-only

```powershell
python tools/casulo_multiboot.py plan --efi-root "X:\" --bundle "release/CASULO_UEFI_COEXISTENCE_BUNDLE_2026-08-22" --output "outputs/casulo/native-multiboot/physical-plan.json"
```

Prossiga somente quando o JSON mostrar:

```text
state = READY_NON_DESTRUCTIVE
overwrites = []
deletes = []
modifies_existing_files = false
fallback_boot_path_touched = false
```

Copie literalmente `confirmation_phrase` do plano. Se o output já existir, use
outro nome; evidência anterior não é sobrescrita.

## 3. Aplicação explícita

```powershell
python tools/casulo_multiboot.py apply --efi-root "X:\" --bundle "release/CASULO_UEFI_COEXISTENCE_BUNDLE_2026-08-22" --plan "outputs/casulo/native-multiboot/physical-plan.json" --confirmation "<FRASE EXATA DO PLANO>" --allow-mounted-efi --receipt "outputs/casulo/native-multiboot/physical-apply-receipt.json"
```

Uma colisão, mudança da árvore depois do plano, hash divergente ou falta de
espaço aborta a operação. O instalador não tenta “consertar” sobrescrevendo.

## 4. Ativação

- systemd-boot: o instalador cria uma entrada nova;
- GRUB: só cria `custom.cfg` se comprovar que o `grub.cfg` existente o consome;
- rEFInd: usa descoberta do namespace vendor, sujeita à configuração local;
- Windows-only ou GRUB não comprovado: o plano retorna
  `UEFI_FIRMWARE_ENTRY_REQUIRED`; nenhuma variável NVRAM ou BCD é alterada.

## 5. Rollback

Use o receipt da aplicação e sua `rollback_confirmation_phrase`:

```powershell
python tools/casulo_multiboot.py rollback --efi-root "X:\" --receipt "outputs/casulo/native-multiboot/physical-apply-receipt.json" --confirmation "<FRASE EXATA DO RECEIPT>" --allow-mounted-efi --output "outputs/casulo/native-multiboot/physical-rollback-receipt.json"
```

O rollback remove somente arquivos criados pela transação e somente se seus
hashes não mudaram. Arquivos preexistentes nunca entram no receipt de remoção.

