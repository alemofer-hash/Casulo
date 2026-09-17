# Reproducibility

## Frozen environment

```powershell
python release/verify_toolchain.py
```

`release/TOOLCHAIN_LOCK.json` records the validated CPython, Rust, QEMU and native-tool versions. `release/requirements-rp01.lock` pins the direct Python packages. Rust components/target and crates are pinned by `os/rust-toolchain.toml` and `os/Cargo.lock`.

## Host correctness

```powershell
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
python tools/casulo_os_baseline.py --verify
python -m pytest -q --basetemp .tmp-tests\reproduce
```

The final local result was `361 passed, 2 skipped, 59 subtests passed`. These are correctness checks, never performance samples.

## TCAP and Casulo Native

```powershell
python tools/rebuild_flood_tcap.py
python tools/verify_flood_tcap.py
python os/tools/build_image.py
python os/tools/run_g2_full_qemu.py --image release/casulo-native-x86_64.img --repeat 5
python os/tools/run_g3_qemu.py --image release/casulo-native-x86_64.img --tcap release/FloodSurrogate.tcap --repeat 3
python os/tools/run_g4_qemu.py --image release/casulo-native-x86_64.img --repeat 5
python os/tools/run_kernel_probes.py
```

The TCAP rebuild command compiles twice in isolated directories and refuses byte differences. The kernel probes build separate panic/reset images outside `release/`; they do not replace the normal image.

## Boot and USB gates

```powershell
python os/tools/run_qemu.py `
  --image release/casulo-native-x86_64.img `
  --repeat 100 --batch-size 5 --cooldown-seconds 15
python os/tools/run_virtual_usb.py `
  --image release/casulo-native-x86_64.img --repeat 10
```

QEMU uses TCG, no network, explicit raw formats, read-only image attachment and a fresh temporary OVMF variable file per boot. The segmented 100-boot command is a correctness gate; temperature and energy remain unavailable.

Virtual USB uses QEMU xHCI plus `usb-storage`, backed only by the read-only regular image. It does not imply physical-device validation.

## LiveLab

```powershell
python livelab/probe_host.py --output evidence/casulo-os-rp01/g5/host-capabilities.json
python livelab/workload_smoke.py numpy-semantic mlp-small
python livelab/freeze_ablation_plan.py
```

Smoke adapters validate scope/equivalence without timing. Do not execute a paired performance campaign until the Thermal Covenant confirms a trusted advancing sensor, cooldown, power parity and low host interference. Do not infer joules from time, temperature or utilization.

## End-to-end local reproduction

```powershell
python release/reproduce.py
python release/reproduce.py --full
```

The first command rebuilds the chain and performs one G7 smoke rehearsal. `--full` runs ten real rehearsals. Neither command writes a physical device or publishes anything.

## Deterministic local release package

```powershell
python release/package_release.py
```

The packager checks every manifest entry and package-tree hash, rejects unsafe/duplicate paths and symlinks, builds two byte-identical ZIPs, validates ZIP contents, extracts to a temporary directory and runs smoke tests using the extracted `src` tree. The archive sidecar contains its SHA-256. Build caches, Rust targets and temporary directories are excluded.
