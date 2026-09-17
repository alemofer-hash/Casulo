# G3 kernel TCAP gate

`qemu-tcap-ring3-*.json` is produced by `os/tools/run_g3_qemu.py`. The runner
preserves complete serial output and requires the outer TCAP hash printed by
the kernel to equal the exact ramdisk file supplied to the image build.

The bounded claim is:

- fail-closed TCAP v1 header, canonical manifest, contract, descriptor,
  SHA-256, target/ABI, permissions and resource validation;
- a separately mapped ring-3 address space, with code RX and context/stack
  RW-NX;
- a per-process syscall mask (`0x03`: mandatory EXIT plus declared console),
  with an actual ring-3 CLOCK request denied as `-EPERM` and one audit event;
- the frozen 8-record, 400-epoch float64 correctness canary agrees with its
  embedded oracle to `1e-9`;
- an independently corrupted in-memory copy is quarantined before payload
  execution.

This is not a general ELF loader, a dynamic linker, a performance campaign,
an energy measurement, a 1,024-record training result, or physical-hardware
validation. The Research Preview loader supports only
`x86_64-casulo-none` plus `casulo-learn-context-sysv64/0.1`, one thread and the
declared `memory`/`console` permission set. QEMU runs use TCG, two virtual CPUs,
no network, no host block device and a read-only workspace image.
