# Limitations — Research Preview 0.1

- QEMU/OVMF validation does not prove boot, SMP, reset or isolation on physical hardware.
- No physical USB has been written or tested. The USB result uses QEMU xHCI and `usb-storage` only.
- No NVMe, SATA, filesystem write, installer, network stack, Secure Boot, TPM or firmware modification is included.
- SMP is bounded to QEMU q35 with exactly two vCPUs, MADT and one xAPIC-started AP; x2APIC, larger topologies and firmware variance are unclaimed.
- The shell is a bounded read-only parser/dispatcher with a boot self-test. Research Preview 0.1 has no interactive line editor or mutable administration commands.
- The panic and reboot proofs use separate QEMU probe images. Normal release execution uses the supported debug-exit path.
- TCAP execution proves one general-IR FloodSurrogate artifact and its frozen 8-record numerical canary. It is not a general proof for arbitrary T programs.
- The historical training gain belongs to a small specialized MLP path. It is preserved as historical evidence and cannot be generalized to the TCAP canary, other architectures, PyTorch Inductor, or Casulo SO.
- G4's `5 versus 10` help case and `6 versus 6` no-help case are deterministic logical operation counts, not wall-clock latency, throughput, energy or S6 evidence.
- LiveLab Linux controls cannot run on this Windows host. Missing cgroups v2, `perf`, RAPL, `sched_ext`, trusted advancing thermal telemetry and external-meter evidence remain `unavailable`/`null`.
- The bounded LiveLab executor and paired statistics are locally verified with correctness smoke processes and explicitly synthetic statistics. No new real Casulo versus PyTorch/Inductor timing campaign ran.
- The nine-axis causal plan is preregistered but unexecuted. It has no effects, confidence intervals or winner until the hardware/safety gate passes.
- Electrical energy is unmeasured; S5 remains `BLOCKED_HARDWARE`. Temperature, TDP and time are not substitutes for joules.
- Multi-host and independent external reproduction remain `BLOCKED_HARDWARE` until an external host executes the package.
- The repository-wide Ruff scan retains 42 legacy warnings outside the Research Preview scope. New Research Preview files pass Ruff; the host test suite and strict Rust lint pass.
- Hash validation proves content identity, not publisher identity. TCAP signing, a secure-boot chain and key management are not part of 0.1.
- The final archive is local and private. No push, publication, PR, paper submission or third-party upload occurred.
