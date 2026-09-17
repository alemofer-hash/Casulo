# Root Cause Report: TCAP 656x Energy Factor

## Finding

The factor is invalid for the declared FloodSurrogate training unit.

The physical campaign executed the TCAP segment explicitly documented as a
bounded correctness canary. That segment contains eight records. The scientific
and historical training uses 1,024 records. Both TCAP and PyTorch workers in the
energy campaign consumed the eight-record canary, so their numerical
equivalence was real for the wrong workload.

The observed TCAP time near 0.27 ms is physically explained as 400 epochs over
eight records in a small, fused, allocation-free raw native kernel. It was not
400 epochs over 1,024 records. The record-count ratio is 128x, closely matching
the roughly 131x gap between the current TCAP timing and the 35.3111 ms
historical C99 timing. Compiler speed alone is neither needed nor sufficient to
explain the discrepancy.

## Classification

`INVALIDATED_INCOMPLETE_WORK_UNIT`

The old energy ratios, confidence interval, sign test and joules-per-training
labels cannot be reused. They remain preserved as measurements of repeated
eight-record canary invocations, not independent 1,024-record trainings.

## Additional findings

- Frozen, dispatched and wrapper-reported K agree in the accepted pairs.
- Energy, power and time algebra recomposes within floating-point error.
- Runtime work counters were absent, so old K completion is not treated as observed.
- Forty-one of 42 accepted implementation windows can be independently
  reintegrated from the preserved CSV. The last accepted Eager window lacks a post-end bracketing sample in the
  extracted CSV and remains recorded, not independently reintegrated.
- The reported thermal `7 C` equals `abs(median(TCAP maxima) - median(Eager maxima))`.
  The median of paired absolute maximum-temperature differences is `6 C`; the
  paired signed median is `3 C`. The old label was ambiguous.

## Corrective actions

1. Reject the correctness canary at every scientific energy-campaign initializer.
2. Require the normative work-unit receipt before timing or energy normalization.
3. Use 1,024-record case files read at runtime, unique nonces/seeds and distinct initial parameters.
4. Require runtime counters and receipt hash chains for TCAP and Eager.
5. Re-run K linearity and synchronization before any physical campaign.
6. Never compare the 0.27 ms canary time directly with the 35.3111 ms historical training.
