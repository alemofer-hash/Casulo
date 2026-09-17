# Casulo SO Research Preview 0.1 — Execution State

Last updated: 2026-08-07

## Global state

- Engineering state: `COMPLETE_LOCAL`
- Last completed gate: `G7_DEMONSTRATION`
- Scientific performance readiness: `BLOCKED_HARDWARE_TELEMETRY`
- Electrical energy readiness: `PASS_HWINFO_500MS_POLLING / BLOCKED_250MS_FALLBACK_CONFIGURATION`
- Physical USB state: `NOT_ATTEMPTED_BY_DESIGN`
- Publication state: `PRIVATE_LOCAL_ONLY`
- Final image SHA-256: `e0a9e2c25baf6a448364fd78a95cdb2bec21f4d2d16669fad11fcf0f3e6f9f0e`
- Final TCAP SHA-256: `2fb6db0d9622382718263dc0ba3b565bdd53ef27bbd9355d40764d1d71643d19`

## Gate table

| Gate | Local state | Authoritative evidence | Scope/remaining boundary |
|---|---|---|---|
| G0 audit/baseline | PASS | `evidence/casulo-os-rp01/g0/baseline.json` | manifest integrity PASS; pre-existing dirty worktree preserved |
| G1 boot | PASS | `evidence/casulo-os-rp01/g1/qemu-boot-100.json`; platform probes | 100/100 final-image boots; panic/reboot QEMU probes; no physical claim |
| G2 isolated kernel | PASS_BOUNDED_QEMU | `evidence/casulo-os-rp01/g2/qemu-g2-full-5.json` | QEMU q35/TCG, exactly two vCPUs; no generic physical SMP claim |
| G3 real T work | PASS_BOUNDED_CANARY | `evidence/casulo-os-rp01/g3/qemu-tcap-ring3-3.json` | real general-IR TCAP and 8-record correctness canary; not performance |
| G4 semantic scheduler | PASS_LOGICAL_REPLAY | `evidence/casulo-os-rp01/g4/kernel/qemu-g4-kernel-5.json` | deterministic logical operation-count replay; wall-clock S6 remains unmeasured |
| G5 LiveLab | PASS_IMPLEMENTATION_AND_HWINFO_SOURCE / BLOCKED_PHYSICAL_THERMAL_CALIBRATION | Energy V1 plus `energy/2026-08-07-g5-hwinfo-tcap-vs-eager/` | HWiNFO CPU-package power and numerical equivalence pass; 81 °C/throttling and 76 °C rejected calibration before K freeze; 0/21 pairs |
| G6 virtual USB release | PASS_VIRTUAL / BLOCKED_PHYSICAL | `evidence/casulo-os-rp01/g6/qemu-virtual-usb-10.json` | 10/10 read-only QEMU xHCI boots; no physical USB written |
| G7 demonstration | PASS | `evidence/casulo-os-rp01/g7/demo-rehearsal-10.json` | 10/10 real QEMU rehearsals; failed path-normalization preflight preserved separately |

## Final validation summary

- Host regression: `361 passed, 2 skipped, 59 subtests passed in 48.43s` with numerical libraries restricted to one thread.
- Rust: `cargo fmt --check`, `cargo check --workspace`, and Clippy with `-D warnings` passed.
- New Research Preview Python scope passes Ruff and `compileall`.
- Repository-wide Ruff exposes 42 pre-existing legacy warnings; they are not hidden by changing compiler provenance after the TCAP freeze.
- G0 verifier: 618 baseline entries checked, zero unexplained tracked divergences.
- Toolchain verifier: CPython packages, Rust nightly, Cargo lock, QEMU, GCC, NASM, CMake and Ninja all match `release/TOOLCHAIN_LOCK.json`.

## G1 and platform evidence

- Final image: 2,162,688 bytes.
- 100/100 boots and framebuffer paint, executed as 20 blocks of five with 15-second cooldowns.
- Evidence SHA-256: `fdedf8a690b5ad3a35c47214be98410a40be8027df3204edf3a8d50fb649176a`.
- The panic probe is a separate non-release image and must emit structured `CASULO_PANIC_DUMP` before debug-exit return code 35.
- The reboot probe uses the 8042 reset path with QEMU `-no-reboot`, must exit zero, and must never return to its call site.
- Platform-probe evidence SHA-256: `96e5f9c80fdce9fa24aa299c7dcc8ca212a3a2b500485537622403efa046cde1`.
- The Casulo shell is a bounded read-only parser/dispatcher with a real kernel self-test; Research Preview 0.1 does not claim an interactive line editor.

## G2 isolation evidence

- ACPI MADT and xAPIC INIT-SIPI start one AP on the bounded two-vCPU target.
- Four ring-3 process executions use private roots; process B cannot access process A.
- A ring-3 page fault is contained without killing kernel progress.
- A non-yielding ring-3 loop is preempted by IRQ0 after the three-tick watchdog budget.
- `YIELD` returns control to the kernel process manager; unknown syscalls and unauthorized per-process syscalls fail closed.
- Final 5/5 evidence SHA-256: `3ea36d5b952cea0fce0f41a3ef49792a1110fb4f58d3c0bf0f997d68daf71473`.

## G3 artifact and execution evidence

- Pipeline: T source → AST → Larva analysis → Crisálida IR 0.2 → Metamorfose graph 0.2 → native plan → freestanding Rust AOT → TCAP v1.
- TCAP: 12,872 bytes; compiler identity includes base HEAD plus canonical dirty source-tree SHA-256.
- Two isolated builds are byte-identical. The payload has zero relocation/GOT/PLT/undefined/low-page dependencies and passes a dynamic-address host audit.
- Kernel maps code RX, data/stack RW+NX in a separate CR3 and applies the declared syscall permission mask.
- The frozen 8-record, 400-epoch float64 canary reproduces loss `0.5514087300000001 → 0.007241680427492191`, parameter maximum difference zero, tolerance `1e-9`.
- Corruption is quarantined with zero payload executions.
- Final 3/3 evidence SHA-256: `4411c1c47eb83a19bbbe8671598b67289e37e424e7ce57a7ae265b7cd311c586`.

## G4 scheduler evidence

- Kernel queues: `FLOW`, `SYSTEM`, `ATTRACTOR_AUDIT`, `ATTRACTOR_RETRY`, `ATTRACTOR_LOW_CONFIDENCE`, and non-executable `QUARANTINE`.
- Hard integrity, permission, quality and isolation gates precede admission.
- Kernel replay matches frozen host vector `c76b1fd397b2a5e84fc6443c027e3d9545ee9dca78f005dfb5c8c962035ae766`.
- Across each replay, 90 ring-3 dispatches yield 90 returns to the kernel; all finite admitted work completes and quarantine dispatches remain zero.
- Interference case: FLOW logical p95 `5` semantic versus `10` FIFO. No-help case: `6` versus `6`.
- These values are logical operation counts, not milliseconds, energy, or proof of S6.
- Final 5/5 evidence SHA-256: `29e3a9e5ce22fa6aa2bc41773d0d985b89bdba70cf09f784baab9dcabcf5101f`.

## G5 LiveLab state

- Nine deterministic workload specifications span FloodSurrogate, three MLP sizes, CNN, attention, dynamic shapes, an unfavorable branch-heavy case, and FLOW/residual interference.
- Seven fail-closed adapters cover NumPy semantic/BLAS, PyTorch Eager/full-step compile, independent C, historical T/C99, and general-IR T/TCAP where semantically applicable.
- The process supervisor applies thread/affinity/cgroup controls before release, monitors thermal/timeout, measures energy only through valid adapters, terminates the child tree, and proves teardown.
- Statistics require at least 21 pairs, median of paired ratios, seeded paired bootstrap CI95 and exact sign test. Compile time and amortization remain separate.
- The nine-axis causal ablation plan is frozen at SHA-256 `1b2eed200792a874b4e76cd9d023233702526aee3493d3db3a8662f604457a60`.
- Current Windows preflight remains `BLOCKED_BEFORE_START`; real workload invocations are zero. No new PyTorch/Inductor timing or energy claim exists.
- Energy V1 adds RAPL hierarchy, wall-meter import/API, battery and thermal
  guards, K calibration, balanced 3 × 21 AB/BA scheduling, idempotent resume,
  paired bootstrap/sign-test judgment and sealed manifests. The final physical
  preflight, calibration, smoke and run all blocked with zero workload and
  `joules=null`; see `docs/research/ENERGY_FINAL_REPORT.md`.
- The Windows HWiNFO adapter validated the live literal field
  `Potência total da CPU [W]` at ~2.001-second median sampling. TCAP and Eager
  passed the 400-epoch numerical gate with maximum parameter difference
  `2.220446049250313e-16` and identical predictions. Calibration remained
  fail-closed after 81 °C with throttling and a later 76 °C probe; K was not
  frozen and no definitive paired sample was started.
- Thermal-recovery campaign R1 isolated 15 newly appended rows and measured
  median/p95 polling intervals of `2.000500/2.005350 s`, above the frozen
  `0.550/0.750 s` limits. It terminated as
  `BLOCKED_HWINFO_POLLING_NOT_CHANGED` with zero workload executions. This is
  preserved historical evidence; the later 500-ms campaigns supersede its
  external-action instruction without overwriting the campaign.
- After reconfiguration, clean 500-ms segments passed at `0.500/0.5071 s`
  median/p95. A contaminated observer attempt was rejected before workload and
  replaced by the `bounded-live-tail-v1` physical guard. The subsequent valid
  60-second idle contained 122 samples at `9.858943313 W` with median `51 C`,
  but an instantaneous `75 C` observation before equivalence terminated the
  500-ms branch with zero training and `0/21` pairs. A separately frozen and
  tested 250-ms fallback is now the only admissible next branch.

## G6/G7 evidence

- Virtual USB: 10/10 through `qemu-xhci/usb-storage`, read-only image, no host block device, no physical write. Evidence SHA-256: `b1b1ec31939cc967e0d9bce9d4460a77d0dacaf84c0914bd0033e67d80d2b92d`.
- G7: 10/10 real rehearsals passed the ordered ten-step contract. Evidence SHA-256: `422fdd08bebbfc4a745d48792416d16565f085b9dc9be839247da699740341cb`.
- The first final G7 attempt produced 10/10 valid serial traces but was blocked by Windows path normalization in the host manifest verifier. That negative is preserved as `demo-rehearsal-10-blocked-path-normalization.*`; the corrected verifier was unit-tested before the successful rerun.

## Safety invariants

1. QEMU accepts only regular image files under the repository and read-only firmware binaries.
2. No `PhysicalDrive`, `/dev/*`, host partition, USB passthrough, NVMe or writable host directory is attached.
3. Missing metrics are `unavailable`/`null`, never zero.
4. Historical performance evidence remains immutable and separate from Research Preview correctness evidence.
5. Performance campaigns remain blocked until trusted advancing telemetry, ≤55 °C cooldown, stable power and low interference all pass.
6. No push, publication, physical write, firmware change or external submission occurred.

## Resume/reproduce commands

```powershell
python release/verify_toolchain.py
python tools/casulo_os_baseline.py --verify
python release/reproduce.py
python release/reproduce.py --full
```

`--full` repeats the ten-run G7 sequence. It does not authorize a physical USB write or a performance campaign.

## G5 HWiNFO campaign update — 2026-08-07

- Corrected a calibration defect that froze the pre-retry `K` instead of the
  `K` from the accepted qualification window. Regression coverage passes and
  the corrected campaign froze `K_TCAP=82356` and `K_Eager=113`.
- Completed 21 valid paired TCAP × PyTorch Eager measurements; 10 definitive
  attempts were rejected and retained. Every accepted pair passed numerical
  equivalence before and after measurement.
- Scientific state is
  `INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS`, not PASS: paired energy
  direction and CI favored TCAP, but median peak-temperature asymmetry was
  7.0 °C against the frozen 3.0 °C limit.
- Authoritative sealed evidence:
  `energy/2026-08-07-g5-hwinfo-thermal-recovery-250ms-90c-start70-kfreeze-fixed/`.
- `TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT` and
  `CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT` remain unchanged.

## Forensic work-unit audit — 2026-08-08

- Terminal state: `INVALIDATED_INCOMPLETE_WORK_UNIT`.
- Root cause: both HWiNFO workers consumed the TCAP's eight-record bounded
  correctness canary. A scientific FloodSurrogate training requires 1,024
  records, so each normalized wrapper unit performed only 1/128 of the required
  record work.
- The factor 656x, its energy ratio, CI and sign test are withdrawn for the
  declared training unit. The raw campaign remains preserved.
- The exact 0.27 ms event was 400 epochs over eight records in the fused raw
  kernel: 3,200 record-visits, not 409,600.
- A fail-closed regression prevents the bounded canary from initializing a new
  energy campaign.
- F10 remains failed on receipts, unique cases, internal counters, three-clock
  synchronization and full-unit K linearity. No corrected 21-pair campaign was
  started.
- Forensic evidence:
  `outputs/casulo/forensic/2026-08-08-tcap-work-unit-forensic-audit/`.

## Full scientific worker — 2026-08-08

- The general T → AST → semantics → IR → graph → TCAP pipeline now carries a
  distinct `SCIENTIFIC_WORK_UNIT` with 1,024 records and 400 epochs.
- Runtime receipts prove 409,600 record visits, 400 forward/backward/optimizer
  steps, and 32,400 parameter writes per completed training.
- K linearity passed in both implementations: TCAP `R²=0.99801055`, Eager
  `R²=0.99870418`; steady slopes are 32.375120 and 274.936526 ms/training.
- Numerical equivalence passed at `1e-9`; maximum parameter difference was
  `4.440892098500626e-16`.
- Energy terminal state: `BLOCKED_THERMAL_OR_SENSOR`. HWiNFO reported
  instantaneous throttling during calibration cooldown, so the Eager
  calibration and all 21 definitive pairs were forbidden.
- Authoritative validation:
  `outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2/`.
- Physical attempt:
  `outputs/casulo/energy/2026-08-08-g5-full-worker-hwinfo-energy/`.

## Definitive full-worker energy gate — 2026-08-08

- Terminal state: `BLOCKED_PHYSICAL_COOLING_REQUIRED`.
- The original 68 °C event is genuine instantaneous thermal throttling, not a
  latched field, power-limit event, timestamp mismatch or parser false positive.
- The watcher critical path is now append-only; the old 256 KiB repeated tail
  read was removed, and 43 targeted tests pass.
- A new 20-minute interval ran with no TCAP or Eager workload. It contained
  4,790 samples, four instantaneous core/P-core 1 throttle samples, and only
  7.293 seconds of maximum symmetric thermal stability versus 30 required.
- Controls completed: 0/3; probes: 0; calibrated K: none; definitive pairs:
  0/21; comparative joules: unavailable.
- Sealed evidence:
  `outputs/casulo/energy/2026-08-08-g5-full-worker-energy-definitive-04/`.
- Single physical action: active cooling and a quiescent host, followed by a
  new campaign identity. No threshold was relaxed and no workload result was
  fabricated.

## Energy host qualification — 2026-08-09

- Terminal state: `BLOCKED_AC_OR_BATTERY`.
- Authoritative attempt:
  `outputs/casulo/preflight/2026-08-09-energy-host-qualification-02/`.
- Exactly one advancing HWiNFO CSV was selected. Sixty-one new samples passed
  the 250 ms polling gate: median 0.250 s and p95 0.2602 s.
- AC was continuous, but battery level rose from 67.5% to 67.8% while charge
  rate remained near 25.9 W. This is the primary blocker.
- Preliminary total CPU utilization was 38.7% median and 49.1% p95, also above
  the frozen 5%/15% quiescence limits. No user, Windows, security, HWiNFO or
  unknown process was terminated.
- The corrected append-only observer passed at 0.951% of one core, maximum
  chunk 3,348 bytes and no memory growth.
- Windows power plan remained Balanced
  (`381b4222-f694-41f0-9685-ff5bb260df2e`); no power setting changed.
- Because P0–P7 failed, the 20-minute idle window was not started and no TCAP,
  Eager, build, test, compilation or packaging command ran.

### Follow-up after battery reached 100%

- Battery gate now passes: 100% constant, 0 W charge/discharge, continuous AC.
- Latest authoritative qualification:
  `outputs/casulo/preflight/2026-08-09-energy-host-qualification-04/`.
- Terminal state changed to `BLOCKED_BACKGROUND_ACTIVITY`.
- Polling, power profile, sensors, thermal flags and append-only observer pass.
- Preliminary CPU remained 30.5% median / 44.06% p95. A separate five-minute
  quiescence wait ended at 35.3% median / 71.66% p95, still with zero thermal
  throttling.
- The 20-minute qualifying idle window and all energy workloads remained
  unstarted.

### Follow-up after manually pausing OneDrive

- OneDrive no longer appeared in the relevant-process inventory.
- Latest authoritative qualification:
  `outputs/casulo/preflight/2026-08-09-energy-host-qualification-06/`.
- Terminal state remains `BLOCKED_BACKGROUND_ACTIVITY`.
- Battery, AC, 250 ms polling, thermal flags and append-only observer passed.
- Preliminary CPU remained 19.3% median / 30.24% p95. HWiNFO64 was the largest
  point-in-time consumer at 23.8% aggregated across logical processors.
- The HWiNFO configuration was not changed and no user or system process was
  terminated.
- The 20-minute idle window and every TCAP/Eager workload remain unstarted.

### CPU-sensor semantics errata and corrected wait

- Attempts through `-07` used HWiNFO `Total CPU Utility` as the background
  activity gate. Their background-activity decisions are invalidated; unrelated
  battery, AC, polling, power, temperature and throttle evidence is preserved.
- The selector now uses literal `Uso total da CPU [%]` / `Total CPU Usage` for
  occupancy and retains `Utilização total da CPU [%]` only as a diagnostic.
- Corrected attempt `-08` still failed: actual usage was 18.5% median and 27.2%
  p95.
- A corrected append-only wait then observed 999 samples with 36.0% median,
  74.31% p95 and 99.9% maximum actual CPU usage.
- Four consecutive instantaneous thermal-throttle samples occurred from
  02:29:04.437 through 02:29:05.196 UTC; package temperature reached 92 °C and
  package power reached 45.742 W.
- Authoritative state: `BLOCKED_THERMAL_THROTTLING`.
- Evidence:
  `outputs/casulo/preflight/2026-08-09-energy-host-quiescence-wait-02.json`.
- No TCAP, Eager, build, test, compilation or packaging workload ran.

### Windows CPU telemetry cross-check — 2026-08-10

- OneDrive was absent after startup was disabled and the process was exited.
- A five-minute corrected wait still ended in `BLOCKED_BACKGROUND_ACTIVITY`.
- A simultaneous 60-second cross-check passed: HWiNFO/Windows median CPU was
  28.8%/28.1%, with p95 34.8%/34.04%.
- Primary measured consumers were Defender (8.09% total capacity), Search
  Indexer (4.92%), Search Protocol Host (4.18%) and HWiNFO (3.12%).
- Security and indexing were not disabled or terminated; no benchmark ran.
- Evidence:
  `outputs/casulo/preflight/2026-08-10-cpu-telemetry-crosscheck-02.json`.

### Low-load floor and process accounting

- A transactional 15-minute wait never reached the frozen median gate; its
  best sustained floor was 7.0% median / 12.31% p95 with zero throttling.
- A 120-second low-load cross-check measured HWiNFO at 6.3% median and Windows
  at 4.1%; the 2.2-point difference exceeded the frozen 2-point consistency
  limit and produced `BLOCKED_SENSOR_SEMANTICS`.
- The lower Windows value was not selected after observation. HWiNFO Total CPU
  Usage remains the preregistered primary quiescence source.
- Largest accounted consumers were HWiNFO (1.79% total capacity), DWM (0.46%),
  Xbox (0.21%), System (0.20%) and the Codex/ChatGPT process group (0.43%).
- The 20-minute qualification and every benchmark remained unstarted.
