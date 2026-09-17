# Casulo Native Research Preview 0.1

The preview is a Rust `no_std` x86-64 kernel booted through UEFI. The build produces only a regular disk-image file under `release/`; it never writes a physical device.

The product-only Native Foundation gate is separate from the historical
research gates. It validates boot, isolation, syscall/capability enforcement and
one TCAP artifact without measuring performance or energy:

```powershell
python os/tools/run_product_alpha_qemu.py `
  --image release/casulo-native-x86_64.img `
  --tcap release/FloodSurrogate.tcap
```

```powershell
python os/tools/build_image.py
python os/tools/run_qemu.py --image release/casulo-native-x86_64.img
python os/tools/run_qemu.py --image release/casulo-native-x86_64.img --repeat 100
python os/tools/run_g2_full_qemu.py --image release/casulo-native-x86_64.img --repeat 5
python os/tools/run_virtual_usb.py --image release/casulo-native-x86_64.img --repeat 10
```

The runner rejects device paths, reparse points and images outside the repository. It attaches the image read-only, disables networking and uses TCG.

The virtual-USB runner uses an emulated QEMU xHCI/USB mass-storage controller. It still accepts only a regular workspace file and does not touch a physical device.

The G2 runner proves the bounded two-vCPU QEMU target: ACPI MADT discovery,
one real xAPIC INIT-SIPI application processor, a ring-3 process under a
private low-address page-table branch, RX/NX mapping policy, and all seven
syscall ABI numbers (including a bounded IPC round trip). It rejects historical
`OPEN`, zero-AP and unimplemented-syscall markers. This is not a claim of
general SMP support on arbitrary physical machines.
