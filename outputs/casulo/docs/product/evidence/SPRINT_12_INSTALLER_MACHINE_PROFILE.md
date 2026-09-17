# Evidencia — Sprint 12 Installer e Machine Profile

Data: 2026-08-11

Estado: `SPRINT_12_INSTALLER_MACHINE_PROFILE_PASS`

## Perfil observado

O doctor real deste host identificou Windows 11 AMD64, Intel Core i5-1235U com
12 processadores logicos, 16.890.978.304 bytes de RAM e aproximadamente 62,3 GB
livres. Python 3.13, Git, CMake, Ninja, Rust e Cargo foram encontrados. Clang e
QEMU continuam ausentes.

Com o cache explicitamente informado, o ASR `base-q5_1` passou novamente:
source, modelo, SHA-256, bridge e ABI carregavel. Assim, `casulo-minimal`,
`casulo-voice` e `casulo-creator` estao `READY`; Guide/Full permanecem
`NEEDS_ACTION` porque nenhum modelo local do Guia foi adotado.

O doctor reportou `mutations_performed=false`, `network_access_performed=false`,
`account_required=false` e `third_party_ai_api_required=false`.

## Instalacao

O plano e read-only e gera consentimento literal ligado ao host e ao perfil.
Sem a frase exata, nenhum diretorio e criado. Com consentimento, o initializer
usa staging confinado, recusa overwrite, cria Living Memory protegida e publica
um receipt sem conta, download ou rede. O teste de produto validou esse fluxo
com envelope explicitamente test-only; a ativacao real usa DPAPI no Windows.

## Reproducao

```powershell
python -m casulo.product.installer doctor --workspace . `
  --voice-manifest release/voice-candidates/whisper-cpp-base-q5_1-v1.9.2.json `
  --voice-cache "$env:LOCALAPPDATA\Casulo\cache\voice"
python -m casulo.product.installer plan --workspace . --feature casulo-minimal
python -m casulo.product.installer calibrate --duration-ms 25
python -m pytest tests/product/test_installer_machine_profile.py -q
```

A microcalibracao durou aproximadamente 25 ms, foi somente uma estimativa local
de UX e nao constitui benchmark cientifico. Nenhum novo pacote foi necessario.
