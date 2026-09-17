# Evidencia — Sprint 13 Casulo Native Foundation

Data: 2026-08-11

Estado: `SPRINT_13_NATIVE_FOUNDATION_PASS`

LLVM 22.1.8 e QEMU 11.0.50/OVMF foram detectados. A imagem foi reconstruida com
Rust `nightly-2026-02-01`, lock preservado e SHA-256:

`ec4141c497d99e6ef70b93fd3048053b5a4c1a4911dd86f7b2450bb0fdf51e2d`

O TCAP anexado possui SHA-256:

`32e9ef414a6ae8c364fcba542fc26768dbea821112b46af2fa5d6ddac3d60dfa`

O boot QEMU/OVMF e o gate product-only passaram. Memoria/paging, framebuffer,
serial, ring 3, CR3 separado, RX/NX, syscall/IPC, fault containment, capability
negativa, TCAP valido, quarentena de corrupcao e shutdown seguro foram
observados. QEMU usou TCG, rede ausente, imagem read-only e nenhum block device
fisico.

Artefato:

`product-demos/native-sprint13/native-acceptance.json`

SHA-256 do receipt: `8cbee030054cf5a09ec13936cda2289d22196182a7d170bc0594684073a9afa7`.

```powershell
python os/tools/build_image.py
python os/tools/run_product_alpha_qemu.py `
  --image release/casulo-native-x86_64.img `
  --tcap release/FloodSurrogate.tcap
```

O gate declara explicitamente `performance_measured=false`,
`energy_measured=false` e `scientific_benchmark=false`.
