# Handoff — Casulo Native First Conversation

## Resultado

O Casulo agora possui uma superfície Stark + Jobs `no_std`, um ABI neural
capability-scoped em ring 3, system pack content-addressed, journal encadeado e
imagem UEFI que passou três boots por USB virtual. A variante NF8 permanece
visível em QEMU para inspeção.

O resultado **não é ainda o primeiro uso oficial**: nenhum token foi derivado
do Qwen dentro do Native, o teclado físico não foi exercido e o journal não foi
gravado/reaberto de mídia. A imagem é um preview visual flashável, não um
Casulo conversacional.

## Abrir o preview visual

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\guimo\Documents\Codex\2026-07-28\ex\outputs\casulo\release\CASULO_NATIVE_OWNER_ALPHA_PREVIEW_2026-08-20-attempt-4\START_PREVIEW_QEMU.ps1"
```

O launcher abre QEMU visível, mantém rede desligada, conecta a imagem como USB
virtual read-only e grava apenas um serial log novo em `%LOCALAPPDATA%\Casulo`.
Fechar a janela QEMU encerra a inspeção.

## Doctor read-only

```powershell
python tools/doctor_native_owner_alpha.py --bundle release/CASULO_NATIVE_OWNER_ALPHA_PREVIEW_2026-08-20-attempt-4 --output outputs/casulo/native-first-conversation/manual-doctor.json
```

## Gate físico, ainda sem escrita

Depois de conectar um pendrive dedicado:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/inspect_native_usb_candidate.ps1
```

O script só usa `Get-Disk`, mascara `UniqueId` por SHA-256 e recusa discos
boot/system ou não USB. Não contém operação de formatação ou escrita. O estado
atual é `NO_ELIGIBLE_USB_PRESENT` porque somente o NVMe interno foi visto.

## Bloqueio que precede o flash

Não faça flash para “usar o Casulo” ainda. O próximo gate precisa provar:

1. GGUF real mapeado read-only em ring 3;
2. tokenizer, Q4_K, RMSNorm, RoPE, atenção, FFN, KV e sampler;
3. primeiro token derivado dos pesos, não de bridge/fixture;
4. stream de tokens no renderer;
5. input físico e persistência após reboot.

Somente uma nova autorização literal, identificando o disk number e a
capacidade do pendrive, poderá liberar escrita física. Secure Boot, firmware,
TPM, BitLocker, NVMe interno e Cloud permanecem intocados.
