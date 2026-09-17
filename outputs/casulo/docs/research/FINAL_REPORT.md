# Casulo SO Research Preview 0.1 — Final local report

State: `COMPLETE_LOCAL`

Date: 2026-08-07

## Architecture delivered

T programs now traverse the formal parser, semantic analysis, versioned general
IR, dependency graph, resource contract, native AOT backend and canonical TCAP
container. Casulo Native boots through UEFI, validates and maps the artifact,
executes its entry point in ring 3 under a private address space and enforces
syscall permissions. The kernel contains memory/interrupt/timer/SMP primitives,
fault containment, IRQ0 watchdog, bounded processes, IPC, a read-only shell,
platform probes and deterministic semantic queues. LiveLab is the separate
capability-driven Linux experiment layer.

## Engineering gates

| Gate | State | Result |
|---|---|---|
| G0 | PASS | Baseline manifest verified; prior dirty worktree preserved; zero unexplained tracked differences |
| G1 | PASS | Final image booted 100/100 with framebuffer; panic and reboot probes executed |
| G2 | PASS_BOUNDED_QEMU | 5/5 with private process roots, contained fault, cross-access denial, real yield and watchdog preemption |
| G3 | PASS_BOUNDED_CANARY | 3/3 real TCAP ring-3 execution, numerical equivalence, permissions and corruption quarantine |
| G4 | PASS_LOGICAL_REPLAY | 5/5 exact host-vector replay, finite progress, zero quarantine dispatch and help/no-help controls |
| G5 | PASS_IMPLEMENTATION / BLOCKED_PHYSICAL_INSTRUMENT | E0–E6 Energy V1, workloads, adapters, executor, paired statistics, controls and manifests implemented; real campaign blocked before start |
| G6 | PASS_VIRTUAL / BLOCKED_PHYSICAL | 10/10 read-only QEMU USB boots; physical USB untouched |
| G7 | PASS | 10/10 complete real-QEMU demonstrations |

Host regression: `361 passed, 2 skipped, 59 subtests passed in 48.43s`.
Rust fmt/check/Clippy strict passed. New Research Preview Python files pass Ruff;
42 legacy repository-wide warnings remain visible.

## New results and scope

- Image: 2,162,688 bytes, SHA-256 `e0a9e2c25baf6a448364fd78a95cdb2bec21f4d2d16669fad11fcf0f3e6f9f0e`.
- TCAP: 12,872 bytes, SHA-256 `2fb6db0d9622382718263dc0ba3b565bdd53ef27bbd9355d40764d1d71643d19`.
- Numerical canary: loss `0.5514087300000001 → 0.007241680427492191`, maximum parameter difference `0`, tolerance `1e-9`.
- Semantic interference replay: FLOW logical p95 `5` versus FIFO `10`; preregistered no-help case `6` versus `6`.
- No wall-clock speedup, confidence interval or energy result was produced by Research Preview 0.1. Correctness repetition counts are not statistical performance samples.
- The Energy V1 campaign `2026-08-07-g5-energy-final` executed every CLI stage
  fail-closed with zero workload and no joules because Windows exposed no
  package RAPL source and no physical wall meter was connected.

## Historical comparison

The historical specialized FloodSurrogate result remains unchanged: median
paired speedup `8.957846×` versus PyTorch Eager, bootstrap CI95
`[8.075179×, 9.872416×]`, 21/21 favorable pairs and exact sign-test
`p = 9.5367431640625e-7`. The partial historical Inductor comparison
`14.255580×` compiled only forward and excluded `10.693516 s` of compilation.

Neither historical number was rerun, replaced or attributed to Casulo Native.
The new TCAP canary has only eight records and exists solely for correctness.

## Paper gaps

Closed locally:

- general `learn` pipeline through executable TCAP;
- bootable Casulo Native executing isolated T work;
- deterministic artifact/container integrity and permission enforcement;
- bounded kernel fault/watchdog/process isolation mechanism;
- kernel implementation of the semantic scheduler's frozen logical policy.

Still open or blocked:

- full-step real `torch.compile` paired campaign;
- measured causal ablations and crossover curves;
- wall-clock S6 scheduler p95/overhead;
- direct electrical energy and two independent sessions;
- related-work novelty analysis against graph compilers/DSLs;
- independent multi-host reproduction and physical boot.

## Authorized claims

- Casulo SO Research Preview 0.1 is a real bootable x86-64 UEFI research OS in the validated QEMU scope.
- The general T pipeline emits a deterministic, content-addressed executable TCAP.
- The frozen FloodSurrogate canary executes in an isolated ring-3 process with the registered numerical result.
- Corrupted artifacts and unauthorized syscalls fail closed.
- The kernel implements and exactly replays the frozen deterministic semantic scheduler policy, including a no-help control.
- The final image is reproducible locally and boots through both virtio and virtual USB transports.
- LiveLab is ready to refuse invalid experiments and to run paired campaigns when the required Linux/hardware gates exist.

## Prohibited claims

- no claim that Casulo SO or the general T compiler is currently `6×`, `8.95×`, or uniformly faster than PyTorch/Inductor;
- no conversion of logical ticks into time or S6 victory;
- no energy or joule advantage;
- no generic physical-hardware SMP, firmware, Secure Boot or production security claim;
- no claim that a physical USB was written or booted;
- no universal ML, flood-prediction or arbitrary-T-program correctness claim;
- no external reproduction, patent grant, publication or commercial validation claim.

## Release artifacts

- `release/casulo-native-x86_64.img`
- `release/casulo-native-x86_64.img.sha256`
- `release/FloodSurrogate.tcap`
- `release/FloodSurrogate.tcap.sha256`
- `release/RELEASE_MANIFEST.json`
- `release/casulo-so-rp01-source-and-demo.zip`
- `release/casulo-so-rp01-source-and-demo.zip.sha256`
- `release/reproduce.py`
- `release/ci_headless.py`

The archive hash is intentionally stored in the external sidecar rather than
inside the archive, avoiding an impossible self-referential digest.

## Single next physical action

Follow the exact meter connection, bare-metal Linux Live preflight command,
duration and expected artifact in `docs/research/ENERGY_FINAL_REPORT.md`. No USB,
firmware, Secure Boot, TPM, BitLocker, partition or internal-disk change was
performed by this workflow.
