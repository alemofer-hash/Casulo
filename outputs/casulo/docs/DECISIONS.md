# Casulo SO Research Preview 0.1 — Architectural Decisions

## ADR-001 — Preserve the existing language and evidence

**Context.** The repository already contains a functional language frontend, scalar/native backends, tensor/autograd infrastructure and historical scientific evidence.

**Decision.** Extend the repository incrementally. Historical protocol IDs, artifact IDs and result directories remain immutable. The legacy `learn -> C99` path remains an explicitly named baseline until the general pipeline proves semantic conformance.

**Consequences.** The preview will contain parallel legacy and general-IR paths during migration. No result may silently mix them.

## ADR-002 — Rust `no_std` modular kernel and UEFI

**Context.** The local machine already has a pinned Rust toolchain, the `x86_64-unknown-none` target and LLVM tools. QEMU/EDK2 is available after a normal package-manager installation.

**Decision.** Implement the kernel in Rust `no_std`, with minimal architecture-specific assembly supplied by mature crates. UEFI is the only boot target for Research Preview 0.1.

**Consequences.** No BIOS-only support, NVMe driver, installer or host-disk writing is included.

## ADR-003 — rust-osdev bootloader 0.11.15 for the first reproducible image

**Context.** Limine is the preferred long-term loader, but the current Windows toolchain lacks the additional POSIX image-building utilities required by its normal workflow. The versioned `bootloader` 0.11.15 crate and its UEFI image builder are already available to the Rust toolchain and work cross-platform.

**Decision.** Use `bootloader = 0.11.15` for Research Preview 0.1. Limine remains an evaluated future migration, not a hidden requirement.

**Consequences.** The preview can produce a deterministic regular-file UEFI image without WSL, host disks or global POSIX tooling. The bootloader choice is not part of the claimed Casulo scheduling novelty.

## ADR-004 — `.tcap v1` is a new bounded container

**Context.** Existing Casulo artifacts are JSON/source bundles and do not define an executable container or resource limits.

**Decision.** Add an independent, versioned `.tcap v1` format: fixed header, canonical JSON manifest, bounded non-overlapping segments and SHA-256 validation. Reject unknown permissions, W+X segments, duplicate JSON keys, overflow and invalid entry points before allocation.

**Consequences.** Existing `casulo-artifact/0.8` and training artifacts remain unchanged. `.tcap` is not a renamed legacy directory.

## ADR-005 — Deterministic semantic scheduling before adaptation

**Context.** Existing worker selection is a numerical-kernel heuristic, not an OS scheduler.

**Decision.** First implement deterministic queues for `FLOW`, `SYSTEM`, `ATTRACTOR_AUDIT`, `ATTRACTOR_RETRY`, `ATTRACTOR_LOW_CONFIDENCE` and `QUARANTINE`, with hard integrity/quality/isolation constraints. Adaptive policy is prohibited until deterministic tests pass.

**Consequences.** Explanations and starvation bounds are observable. No claim of OS advantage is authorized before controlled interference evidence.

## ADR-006 — LiveLab is Linux-first and capability-driven

**Context.** cgroups v2, RAPL powercap, perf, uclamp and sched_ext are Linux capabilities and cannot be honestly emulated on Windows.

**Decision.** LiveLab reports a four-state capability contract (`available`, `unavailable`, `blocked_permission`, `error`). Windows supports only capabilities actually present; Linux controls are implemented and testable against fake sysfs before real execution.

**Consequences.** The current Windows host can build and test the adapters but cannot produce Linux scheduler/energy claims. Such gates remain `BLOCKED_HARDWARE`/`BLOCKED_ENVIRONMENT` as appropriate.

## ADR-007 - Virtual USB means an emulated USB transport, not a renamed disk boot

**Context.** A raw image booted through virtio proves the image and UEFI path, but does not exercise USB mass-storage discovery. Attaching a host device would violate the goal's safety boundary.

**Decision.** The G6 runner attaches only a regular workspace image, read-only, through QEMU xHCI and `usb-storage`. It rejects device-path spellings and records the image hash and transport in machine-readable evidence.

**Consequences.** A passing virtual-USB test is reproducible and non-destructive. It does not authorize or imply physical media, firmware or Secure Boot validation.

## ADR-008 - G2 SMP is a bounded QEMU proof

**Context.** Correct multiprocessor startup depends on firmware tables, interrupt-controller mode and platform topology. The local safety target is a deterministic QEMU q35 machine with two virtual CPUs, not arbitrary physical hardware.

**Decision.** Parse ACPI MADT and start exactly one application processor with a real xAPIC INIT-SIPI sequence and a 16/32/64-bit low-memory trampoline. The full G2 validator requires one BSP plus one AP and records `smp_general_machine_support_claimed=false`.

**Consequences.** G2 proves the mechanism and isolation contract in the frozen QEMU target. It does not claim x2APIC, more than one AP, firmware variance or physical-machine compatibility.

## ADR-009 - Numerical canary is correctness evidence, not a benchmark

**Context.** The real FloodSurrogate payload needs bounded inputs and independently known outputs for repeatable kernel validation. Replaying the historical 1,024-record campaign in every boot would mix correctness, performance and thermal concerns.

**Decision.** Embed an eight-record float64 canary with initial parameters, frozen 400-epoch contract and expected outputs in a read-only TCAP segment. The kernel must execute the same AOT payload in ring 3 and compare within `1e-9` before any timing marker may appear.

**Consequences.** A PASS proves bounded numerical execution and equivalence for the canary. It does not reproduce or extend the historical speedup and cannot be reported as performance evidence.

## ADR-010 — Dirty compiler provenance is content-addressed

**Context.** The Research Preview compiler is newer than the repository's base HEAD. Recording only that HEAD would falsely attribute generated code to an older tree.

**Decision.** The TCAP compiler identity is the base commit followed by `+dirty-tree-<sha256>`, where the digest canonically covers every Python source under `src/casulo/t` plus `pyproject.toml`. Source, IR, graph, plan, canary and native payload also retain independent hashes.

**Consequences.** A dirty but reproducible local build is honestly identified without requiring an artificial commit. Any compiler-source change invalidates the identity and requires a TCAP and kernel-image rebuild.

## ADR-011 — G2 containment uses explicit recovery contracts

**Context.** A ring-3 happy-path syscall demo does not prove isolation. A user page fault or non-cooperative loop must not kill or monopolize the kernel, and separate processes must not share private mappings.

**Decision.** The bounded QEMU kernel uses separate address-space roots, expected-fault recovery state, an IRQ0 watchdog budget, and a kernel-returning `YIELD`. Adversarial probes require cross-process denial, contained user fault, exact bounded watchdog preemption, and post-fault kernel progress.

**Consequences.** G2 is a real containment proof for the frozen QEMU q35 two-vCPU target. It remains explicitly narrower than arbitrary hardware, x2APIC topologies, or production-grade process lifecycle management.

## ADR-012 — G4 novelty is first proved as deterministic logical replay

**Context.** Wall-clock scheduler comparisons on the current Windows laptop cannot satisfy thermal, Linux-control, or energy requirements. Calling logical ticks milliseconds would fabricate S6 evidence.

**Decision.** Freeze one host reference vector and replay both conventional FIFO and semantic policies inside ring 3. Require exact trace agreement, hard gates, bounded audit progress, zero quarantine dispatch, a preregistered help case and a no-help case. Label every result as logical operation count.

**Consequences.** The implementation and causal mechanism are demonstrable now; wall-clock p95 advantage, overhead, energy and S6 remain blocked until a valid LiveLab campaign exists.

## ADR-013 — Platform exit paths use isolated probes

**Context.** Intentionally panicking or rebooting the normal demo image would contaminate G1–G7 traces and prevent deterministic supported exit.

**Decision.** Build separate non-release panic and reboot probe images. The panic probe must produce a structured dump and debug-exit code 35. The reboot probe must use the 8042 reset command under QEMU `-no-reboot`, exit zero and never return. The normal release image uses `isa-debug-exit` after its demonstration.

**Consequences.** Panic and reset paths are executed rather than asserted, while the release image remains deterministic. The proof is QEMU-specific and does not claim firmware or physical reset compatibility.

## ADR-014 — Release packages are self-verifying and content complete

**Context.** A ZIP containing only binaries is insufficient for independent reproduction, and checking only the image and TCAP can miss stale source or evidence.

**Decision.** Include sources, tests, examples, benchmark history, Research Preview evidence, specs and release tools. The manifest hashes every selected regular file, records a package-tree digest and dirty repository identity, rejects unsafe/duplicate paths and symlinks, and states that neither publication nor physical writes occurred. Build the ZIP twice and compare bytes, then extract it safely and run smoke tests from the extracted `src` tree.

**Consequences.** The local archive is reproducible and auditable without claiming external reproduction. Multi-host and physical-media validation remain separate human/hardware gates.
