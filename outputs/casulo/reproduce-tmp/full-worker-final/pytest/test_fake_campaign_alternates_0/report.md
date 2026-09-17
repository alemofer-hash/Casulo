# LiveLab campaign `deterministic`

Status: **complete**

Evidence kind: **measured**

Workload started: **yes**

## Preflight gates

| Gate | Status | Reason |
|---|---|---|
| capabilities | pass | `all_required_available` |
| thermal | pass | `thermal_stream_stable` |
| power_state | pass | `power_state_stable` |
| isolation | pass | `isolation_verified` |

## Result

- Trials per label: 3
- Median paired speedup (baseline/candidate): 6x
- Energy ratio: 6.0
- Valid pairs: 3 (minimum for inference: 21)
- Statistical claim: descriptive_only_insufficient_or_not_requested
- Compile cost totals (ns): {"casulo": 0, "torch": 0}
- Compile amortization count: 1
- Amortized speedup: 6x
- Interpretation: descriptive only; no significance inference.
