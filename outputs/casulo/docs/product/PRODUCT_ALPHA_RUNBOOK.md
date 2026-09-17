# Product Alpha runbook

## Hosted owner

```powershell
$env:PYTHONPATH='src;private/casulo-owner/src;services/casulo-cloud-standby/src;editions/casulo-public/src'
python -m casulo_owner.alpha_demo --output product-demos/product-alpha-owner-new
```

O comando recusa output nao vazio, usa DPAPI, nao usa Cloud/API de terceiro e
produz `alpha-report.json` mais `SHA256SUMS`.

## Doctor completo

```powershell
python -m casulo.product.installer doctor --workspace . `
  --voice-manifest release/voice-candidates/whisper-cpp-base-q5_1-v1.9.2.json `
  --voice-cache "$env:LOCALAPPDATA\Casulo\cache\voice" `
  --guide-registry models/registry.json
```

Doctor e plan sao read-only. `initialize` exige a frase literal gerada por
`plan`; nao copie uma frase antiga de outra maquina/perfil.

## Native

```powershell
python os/tools/build_image.py
python os/tools/run_product_alpha_qemu.py `
  --image release/casulo-native-x86_64.img `
  --tcap release/FloodSurrogate.tcap
```

Somente arquivos regulares sob o repositorio sao aceitos. O runner usa imagem
read-only e rede desativada; nunca forneca PhysicalDrive ou `/dev/*`.

## Edicoes

`tools/build_product_editions.py` exige tres chaves explicitas e externas ao
repositorio. Os artefatos Alpha existentes estao em
`product-demos/release-sprint14`. Chaves privadas nao fazem parte do pacote.

## Gate de regressao

```powershell
python -m pytest -q tests/product tests/test_os_qemu_safety.py `
  tests/test_t_frontend.py tests/test_t_semantics_ir.py tests/test_t_workspace.py `
  tests/test_t_tcap.py tests/test_t_backend.py tests/test_t_metamorphosis.py `
  tests/test_t_native.py tests/test_semantic_scheduler.py
cargo +nightly-2026-02-01 -Z bindeps check --manifest-path os/Cargo.toml --locked
python tools/audit_public_artifact.py product-demos/release-sprint14/public/casulo_public-0.1.0a1-py3-none-any.whl
```

Nenhum comando acima inicia campanha cientifica, RAPL, HWiNFO, PyTorch ou
medicao de superioridade.
