# Kernel isolation hardening and G4 replay

Status: bounded QEMU x86-64 correctness gate. This specification does not
claim arbitrary-machine SMP support, wall-clock acceleration, energy
improvement, Linux scheduler equivalence or S6.

## Adversarial G2 boundary

The kernel creates two distinct low-half user page-table roots. Process A owns
a read-only, non-executable probe page at `0x00600000`; process B has no
translation for that virtual address. The test is architectural, not only a
CR3 comparison:

1. process A reads a frozen sentinel from its private page and exits normally;
2. process B executes the same user-mode load with the page absent;
3. the ring-3 page fault is recognized only when CPL is 3 and CR2 equals the
   armed address;
4. the handler redirects that process to a mapped termination stub;
5. the kernel and a subsequent process continue.

Any unarmed or mismatched page fault remains fatal. The handler does not skip
an arbitrary instruction or turn an unexpected fault into success.

The non-cooperative probe is an infinite ring-3 `pause` loop. IRQ0 observes a
three-tick watchdog budget, redirects only a CPL3 frame to a bounded
termination stub, and records the actual elapsed PIT ticks. The strict runner
accepts only 3 through 5 ticks and then requires a subsequent ring-3 task to
complete. These are hardware timer ticks for the containment bound; they are
not benchmark latency.

Syscall 3 (`YIELD`) sets a trap action in the syscall entry path and returns to
the saved kernel stack and kernel CR3. The G2 canary resumes its continuation;
the G4 manager deliberately retires each one-operation slice after control has
returned. A YIELD that merely returns directly to user mode cannot satisfy the
G4 counter equality.

## Bounded task manager

The kernel manager has fixed capacities of 16 tasks, 32 trace events per run
and a 64-entry conventional ready queue. Admission applies independent hard
gates for integrity, permissions, quality and isolation. Any failure, or an
explicit `QUARANTINE` request, creates a non-runnable quarantine record.
Ranking cannot override a gate.

The conventional comparator is flat FIFO round-robin. The semantic policy has
the runnable classes `FLOW`, `SYSTEM`, `RETRY`, `LOW_CONFIDENCE` and
`ATTRACTOR_AUDIT`, with a periodic audit reservation every four logical
dispatches. Within one class it ranks earliest deadline, then highest priority,
then admission sequence. Each dispatch consumes exactly one bounded budget
unit and executes one real ring-3 slice ending in YIELD.

## Frozen-vector conformance

The host reference is immutable at SHA-256
`c76b1fd397b2a5e84fc6443c027e3d9545ee9dca78f005dfb5c8c962035ae766`.
Kernel code contains independent expected task sequences and selection-check
counts for both preregistered scenarios. It compares every produced event's
logical tick, task identity, class, decision, remaining budget, priority,
deadline, deadline state and selection checks.

Required relations:

- controlled interference: semantic FLOW p95-style completion count 5,
  conventional 10;
- no-help control: semantic 6, conventional 6;
- audit service gap no greater than four logical dispatches;
- all bounded finite admitted work completes;
- five invalid/requested-quarantine tasks produce zero dispatches;
- 90 kernel dispatches produce exactly 90 ring-3 YIELD returns.

The p95-style values are deterministic logical operation counts. The serial
protocol explicitly says `logical-operation-count-not-wall-clock`; timing and
energy remain `unavailable`.

## Reproduction

```powershell
python os/tools/build_image.py
python os/tools/run_g2_full_qemu.py --image release/casulo-native-x86_64.img --repeat 5 --timeout 40
python os/tools/run_g3_qemu.py --image release/casulo-native-x86_64.img --tcap release/FloodSurrogate.tcap --repeat 3 --timeout 40
python os/tools/run_g4_qemu.py --image release/casulo-native-x86_64.img --repeat 5 --timeout 40
```

The runners attach the regular-file image read-only under QEMU TCG, disable
networking and never attach a host block device. G4 also mutates required
markers, the reference digest, quarantine count, watchdog bound and supported
exit status to prove the validator fails closed.

## Deliberately open

- safe shutdown is implemented for the normal QEMU gate through
  `isa-debug-exit`;
- a separate reboot-probe image requests an 8042 reset and passes only when
  QEMU `-no-reboot` exits zero without the call returning;
- a separate panic-probe image passes only when the real panic handler emits
  the structured dump and exits through the failure code (host return 35);
- the Casulo shell is a bounded, allocation-free parser/dispatcher for the
  read-only commands `help`, `status`, `topology` and `scheduler`; its positive
  and negative self-tests run in the normal image;
- interactive serial line editing and mutation commands are not claimed.

The probe images are compiled with the fail-closed `CASULO_BOOT_PROBE` build
mode and stored only as local evidence. They never replace or modify the
normal release image. Reproduce them with:

```powershell
python os/tools/build_probe_image.py panic
python os/tools/build_probe_image.py reboot
python os/tools/run_kernel_probes.py `
  --panic-image evidence/casulo-os-rp01/g2/platform-probes/casulo-panic-probe.img `
  --reboot-image evidence/casulo-os-rp01/g2/platform-probes/casulo-reboot-probe.img
```
