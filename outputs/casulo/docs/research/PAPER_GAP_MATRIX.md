# Casulo/T paper gap matrix

States: `OPEN`, `PASS`, `FAIL`, `BLOCKED_HARDWARE`, `NOT_APPLICABLE`.

| ID | Scientific gap | State | Required evidence | Current/target files |
|---|---|---|---|---|
| P1 | Full `forward + backward + optimizer` PyTorch compiled baseline | BLOCKED_HARDWARE | full-step adapter and fail-closed executor exist; real equivalence plus paired samples require valid Linux/thermal controls | `src/casulo/livelab/baselines.py`; `src/casulo/livelab/workload_adapters.py`; `tests/test_livelab_baselines.py` |
| P2 | `learn` through general AST/semantics/IR/graph | PASS | general 0.2 path produces deterministic native TCAP and executes its canary in isolated ring 3 | `src/casulo/t/learn.py`; `src/casulo/t/learn_native.py`; `evidence/casulo-os-rp01/g3/qemu-tcap-ring3-3.json` |
| P3 | Isolate causal mechanism | BLOCKED_HARDWARE | nine-axis preregistration and profiling contract exist; effects/CI require the gated campaign | `src/casulo/livelab/ablations.py`; `evidence/casulo-os-rp01/g5/ablation-preregistration/plan.json` |
| P4 | Multiple architectures and unfavorable case | BLOCKED_HARDWARE | nine versioned specs and correctness adapters exist; paired crossover curves remain unmeasured | `src/casulo/livelab/workloads.py`; `src/casulo/livelab/workload_adapters.py`; `docs/research/LIVELAB_WORKLOAD_PROTOCOL.md` |
| P5 | Multiple hosts | BLOCKED_HARDWARE | independent signed manifests | future external reproduction package |
| P6 | Direct electrical energy | BLOCKED_HARDWARE | E0–E6 stack, physical-source rejection, battery/thermal guards, resumable 3 × 21 runner and judge pass locally; valid advancing RAPL or physical meter remains absent | `src/casulo/livelab/energy_v1/`; `energy/2026-08-07-g5-energy-final/`; `docs/research/ENERGY_FINAL_REPORT.md` |
| P7 | Independent reproduction | BLOCKED_HARDWARE | deterministic local package exists; an external host result is still required | `release/package_release.py`; `release/reproduce.py` |
| P8 | Novelty versus graph compilers/DSLs | OPEN | mechanism-level related-work comparison | `paper_artifacts/literature/`; future manuscript |
| P9 | OS-level semantic decision versus conventional policy | BLOCKED_HARDWARE | kernel matches the frozen logical replay including help/no-help; measured wall-clock p95 and overhead still require LiveLab | `evidence/casulo-os-rp01/g4/kernel/qemu-g4-kernel-5.json`; future scheduler campaign |
| P10 | Bootable Casulo Native running isolated T work | PASS | final image boots 100/100; real TCAP executes in isolated ring 3 with equivalence and quarantine | `evidence/casulo-os-rp01/g1/qemu-boot-100.json`; `evidence/casulo-os-rp01/g3/qemu-tcap-ring3-3.json` |
| P11 | Historical FloodSurrogate evidence preserved | PASS | immutable hashes and independent recalculation | `paper_artifacts/dist/`; historical result directories |
| P12 | Thermal attempt correctly treated as no benchmark | PASS | `BLOCKED_BEFORE_START`, zero child runtime | `benchmarks/results/2026-08-02-sprint025-ablation/` |
| P13 | HWiNFO-reported Windows CPU-package energy for TCAP versus Eager | BLOCKED_HARDWARE | live source and equivalence pass; a thermally stable calibration, frozen K and 21 valid pairs are still required | `energy/2026-08-07-g5-hwinfo-tcap-vs-eager/` |
| P14 | Faster HWiNFO sampling for thermal recovery | BLOCKED_HARDWARE | R1 requires median <=0.550 s and p95 <=0.750 s before load; observed 2.000500/2.005350 s, so no workload was authorized | `energy/2026-08-07-g5-hwinfo-thermal-recovery/` |
| P15 | Thermally valid high-frequency HWiNFO campaign | BLOCKED_HARDWARE | 500-ms polling passed, but a 75 C pre-workload observation rejected that branch; the fully implemented separate 250-ms fallback still requires the physical HWiNFO setting and a valid 20-second probe | `energy/2026-08-07-g5-hwinfo-thermal-recovery-02/`; `energy/2026-08-07-g5-hwinfo-thermal-recovery-03/`; `src/casulo/livelab/energy_v1/hwinfo_recovery.py` |

No row may move to `PASS` based only on a plan, mock, unit test narrower than the claim, or absence of detected failure.

The energy implementation closes the software/instrumentation gap, not P6's
physical-evidence gap. Its terminal state is `BLOCKED_PHYSICAL_INSTRUMENT`.

## Energy claim gap after the corrected HWiNFO campaign

| Proposed claim | Evidence now available | Remaining gap |
|---|---|---|
| T/TCAP uses less CPU-package energy than PyTorch Eager for FloodSurrogate on this host | 21 valid AB/BA pairs; equivalence pre/post; paired CI below 1; sign test 21/21 | Frozen thermal-parity gate failed, so the claim remains inconclusive |
| Total-machine energy advantage | None from HWiNFO package power | Calibrated wall meter and controlled battery |
| Casulo Native energy advantage | None | Same physical hardware, external wall meter and Native/Linux cross-validation |
| Generalization beyond FloodSurrogate | None from this campaign | Preregistered workloads, hosts and independent replication |
| Advantage over Inductor | Not measured here | Equivalent `torch.compile`/Inductor campaign with compile cost separated |

The next admissible confirmatory experiment must use a new campaign identity,
freeze its thermal-parity design before observing energy, and preserve this
inconclusive campaign unchanged.

## Forensic correction — 2026-08-08

| ID | Scientific gap | State | Required evidence | Current/target files |
|---|---|---|---|---|
| P16 | Full 1,024-record TCAP energy work unit | PASS | internal 400-epoch/409,600-record counters, unique cases, receipts, hash chain and K linearity passed | `docs/spec/FLOOD_WORK_UNIT_V1.md`; `outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2/` |
| P17 | Validity of 2026-08-07 factor 656x | FAIL | old worker used 8-record correctness canary; result is formally invalidated | `docs/research/ENERGY_ERRATA.md`; `docs/research/ROOT_CAUSE_REPORT.md` |
| P18 | Corrected TCAP versus Eager package-energy campaign | BLOCKED_HARDWARE | full-work gates passed; instantaneous HWiNFO throttling stopped calibration before 0/21 pairs | `outputs/casulo/energy/2026-08-08-g5-full-worker-hwinfo-energy/` |

The previous HWiNFO row cannot support any energy-advantage claim. Thermal
parity was not the only unresolved gate: the work-unit denominator itself was
wrong.

## Full-worker correction — 2026-08-08

| ID | Scientific gap | State | Evidence |
|---|---|---|---|
| P16 | Full 1,024-record TCAP work unit | PASS | internal counters, receipts, unique cases, three clocks, equivalence and K linearity passed in `2026-08-08-flood-full-worker-v1-r2` |
| P18 | Corrected TCAP versus Eager package energy | BLOCKED_HARDWARE | calibration stopped on instantaneous HWiNFO throttling before Eager and before any definitive pair |

The current timing slopes are 32.375120 ms TCAP and 274.936526 ms Eager for
the complete work unit. Energy remains unjudged: 0/21 definitive pairs.

## Definitive thermal forensics — 2026-08-08

| ID | Scientific gap | State | Evidence |
|---|---|---|---|
| P18 | Corrected TCAP versus Eager package energy | BLOCKED_HARDWARE | the 68 °C event is genuine instantaneous thermal throttling; a later 20-minute no-workload interval contained four additional instantaneous core-throttling samples and never sustained the 30-second stable-start gate |
| P19 | Incremental HWiNFO observer budget | BLOCKED_HARDWARE | append-only reader and 43 regressions pass; CPU/power/median-temperature budgets passed in a complete A/B/C diagnostic, but its frozen maximum-temperature delta failed and a thermally symmetric repeat could not start |

The required next step is physical: active cooling plus a quiescent host. No
software or statistical adjustment can convert the current 0/21 result into
energy evidence.
