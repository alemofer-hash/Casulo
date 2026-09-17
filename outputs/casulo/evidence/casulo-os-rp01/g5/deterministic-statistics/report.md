# LiveLab campaign `synthetic-statistics-v1`

Status: **complete**

Evidence kind: **synthetic**

Workload started: **yes**

## Preflight gates

| Gate | Status | Reason |
|---|---|---|
| capabilities | pass | `all_required_available` |
| thermal | pass | `thermal_stream_stable` |
| power_state | pass | `power_state_stable` |
| isolation | pass | `isolation_verified` |

## Result

**SYNTHETIC DATA: reporting/statistics test only; not benchmark evidence.**

- Trials per label: 21
- Median paired speedup (baseline/candidate): 1.90909x
- Energy ratio: 1.909090909090909
- Valid pairs: 21 (minimum for inference: 21)
- Statistical claim: synthetic_paired_inference_test_only
- Seeded paired bootstrap CI95: [1.87719, 1.9434] (seed=20260807, resamples=10000)
- Exact sign test: wins=21, losses=0, ties=0, two-sided p=9.53674e-07
- Compile cost totals (ns): {"baseline": 500000, "candidate": 800000}
- Compile amortization count: 100
- Amortized speedup: 1.89982x
