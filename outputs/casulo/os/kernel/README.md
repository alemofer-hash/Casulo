# Casulo kernel G2 bounded gate

This directory contains the incremental, boot-tested G2 kernel foundation for the
Research Preview. It extends the G1 UEFI boot without changing its serial contract.

Implemented and exercised in QEMU:

- allocation only from page-aligned UEFI `Usable` physical regions;
- live page-table access through the bootloader physical-memory mapping;
- a bounded 64 KiB kernel-only heap and an adjacent unmapped guard page;
- GDT with kernel/user descriptors, TSS and an IST-backed double-fault entry;
- IDT, software breakpoint, remapped 8259 PIC and 100 Hz PIT IRQ0 ticks;
- a deterministic progress-watchdog contract;
- CPUID topology discovery;
- a deliberate guard-page page fault whose handler validates CR2 and redirects only
  the pre-armed test probe to a fixed recovery point.

The page-fault probe remains only exception-containment evidence. Process isolation
is separately exercised by a real ring-3 canary under a distinct CR3 and private
low-address paging branch. Its code is user RX, its stack is user RW/NX, and the
kernel view never grants user access to the same addresses. Calls 0 through 6 of the
frozen ABI are implemented through `syscall`/`sysretq`; the canary also proves
`-ENOSYS`, IPC round trip, trace and exit 42.

The SMP proof parses ACPI MADT and starts exactly one QEMU AP through xAPIC
INIT-SIPI and a 16/32/64-bit low-memory trampoline. Therefore
`G2_FULL_GATE=PASS` is a bounded two-vCPU QEMU statement, not a claim of arbitrary
physical-machine SMP support.

Run from the repository root:

```powershell
python os/tools/build_image.py
python os/tools/run_qemu.py --image release/casulo-native-x86_64.img
python os/tools/run_g2_full_qemu.py --image release/casulo-native-x86_64.img --repeat 5
```

Both runners attach only the workspace image as a read-only virtual block device.
