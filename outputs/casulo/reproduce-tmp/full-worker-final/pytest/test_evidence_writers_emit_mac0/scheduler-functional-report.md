# G4 semantic scheduler functional reference

Status: **PASS**

Scope: deterministic tick-level correctness only. No wall-clock, energy, kernel-equivalence or S6 claim is made.

## Pre-registered causal scenarios

| Scenario | Expected | Semantic FLOW p95 ticks | Conventional FLOW p95 ticks | Holds |
|---|---|---:|---:|---|
| controlled_interference_help | `semantic_flow_p95_lt_conventional_flow_p95` | 5 | 10 | True |
| controlled_no_help | `semantic_flow_p95_eq_conventional_flow_p95` | 6 | 6 | True |

## Safety and liveness

- Hard gates hold: True
- Quarantine dispatches: 0 = True
- Audit service bound holds: True
- Finite admitted workload completes: True

The overhead field is an operation-count proxy, not duration. It permits deterministic implementation comparison without disguising unavailable measurements as performance data.

## Required kernel markers

- `CASULO_G4_POLICY_ID=semantic_v1`
- `CASULO_G4_HARD_GATES=integrity,permissions,quality,isolation`
- `CASULO_G4_AUDIT_BOUND_TICKS=<configured_interval>`
- `CASULO_G4_QUARANTINE_DISPATCHES=0`
- `CASULO_G4_REFERENCE_VECTOR_SHA256=c76b1fd397b2a5e84fc6443c027e3d9545ee9dca78f005dfb5c8c962035ae766`
