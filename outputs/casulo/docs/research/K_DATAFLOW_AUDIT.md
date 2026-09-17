# K Dataflow Audit

## Original 2026-08-07 route

The recovered dataflow is:

```text
target window
  -> calibrated seconds per wrapper call
  -> qualification count
  -> frozen_k.json: K_TCAP=82356, K_Eager=113
  -> recovery collector selects frozen K
  -> PersistentWorker sends ASCII `RUN K`
  -> TCAP Rust wrapper parses K and loops `for _ in 0..k`
  -> each iteration resets parameters and invokes the raw TCAP entry
  -> worker reports the requested K
  -> HWiNFO window joules and duration are divided by K
  -> analysis.json labels the quotients J/training and s/training
```

The stale-K calibration defect found earlier was already fixed by freezing
`qualification["K"]`. The sealed campaign used the corrected frozen values;
there is no second division by 400 and no mismatch between frozen, dispatched
and wrapper-reported K in the 21 accepted pairs.

## Defect

The divisor itself counted wrapper invocations of the eight-record correctness
canary. It did not count the normative 1,024-record work unit. Static code shows
that every TCAP wrapper iteration calls the kernel with:

```text
records = 8
epochs  = 400
```

The wrapper therefore performs 3,200 record-visits per divided unit, while the
declared work unit requires 409,600. `K` was internally consistent but had the
wrong scientific dimension. The defect is a work-unit substitution, not a
double-division arithmetic error.

## Observability gap

The old worker emitted only its parsed/requested `K`, final result and elapsed
time. It did not emit runtime counters for epochs, optimizer steps or records.
Consequently `K_started`, `K_completed`, `epochs_completed`,
`optimizer_steps` and `records_visited` remain `null` in the forensic
recomposition. They are not inferred from wrapper control flow.

## Preventive correction

The energy initializer now fails closed when a TCAP contains fewer than 1,024
records, with a regression test reproducing the original acceptance before the
fix. The private bypass exists only for non-performance parser/protocol tests
and is not exposed by the campaign CLI.
