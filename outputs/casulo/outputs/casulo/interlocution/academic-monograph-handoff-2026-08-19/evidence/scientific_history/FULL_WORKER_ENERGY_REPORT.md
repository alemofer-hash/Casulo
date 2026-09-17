# Full-worker HWiNFO energy report

**Terminal state:** `BLOCKED_THERMAL_OR_SENSOR`

The full-worker performance and equivalence gates passed. The definitive
21-pair energy schedule did not start.

The corrected HWiNFO watcher observed `Potência total da CPU [W]` at a median
interval of approximately 0.251 s. A 60-second idle window passed with 241
samples and 9.052605 W average package power.

The TCAP calibration completed 620 independent full trainings in 17.228396 s,
with 620 receipts, 71 energy samples, full coverage, 276.293030 J total, and
0.445633919 J per training. This isolated number is calibration only and is not
comparative evidence.

During cooldown, before the Eager calibration began, HWiNFO reported
instantaneous thermal throttling at `2026-08-08T14:19:54.187Z` and 68 °C. The
frozen rule requires zero throttling. The campaign stopped with 0/21 definitive
pairs and therefore has no TCAP/Eager joule ratio or energy conclusion.

`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT` and
`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT` remain invariant.

Evidence:
`outputs/casulo/energy/2026-08-08-g5-full-worker-hwinfo-energy/`.

