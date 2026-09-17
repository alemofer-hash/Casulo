# Forensic Energy Audit — TCAP versus PyTorch Eager

## Verdict

`INVALIDATED_INCOMPLETE_WORK_UNIT`

The campaign was internally consistent as an eight-record canary experiment,
but it did not execute the declared 1,024-record FloodSurrogate training unit.
No new 21-pair energy campaign is scientifically authorized until the F10 work
receipt, unique-case, linearity and synchronization gates pass.

## What happened during the reported 0.27 ms

The TCAP wrapper reset 81 parameters, allocated/reset an 81-element gradient
buffer and synchronously called a 2,680-byte raw native kernel. The kernel ran
400 epochs, but each epoch traversed only eight records. It therefore executed
3,200 record-visits, 400 forward/backward epochs and 400 parameter updates for
the bounded fixture. It did not execute 409,600 record-visits.

The small allocation-free kernel explains why this fixture can complete in a
fraction of a millisecond. Multiplying the workload by the missing record ratio
of 128 predicts a time on the order of the independently measured historical
35.3111 ms C99 route. This is a causal reconciliation, not a corrected timing
claim.

## Preserved evidence

The original seal passes. The forensic inventory hashes every original file.
Pair recomposition independently integrates 41 of 42 preserved HWiNFO windows;
the final Eager arm lacks a post-end bracketing sample in the extracted CSV.
Missing work counters remain null. No original file was changed.

## Gate status

```text
WORK_UNIT_SPEC             PASS
K_DATAFLOW                 FAIL_WRONG_DIMENSION
K_LINEARITY                NOT_AUTHORIZED_FOR_OLD_UNIT
UNIQUE_CASES               FAIL_IDENTICAL_CANARY
RECEIPTS                   FAIL_NOT_IMPLEMENTED
SYNCHRONIZATION            PARTIAL_PARENT_AND_CHILD_ONLY
EQUIVALENCE                PASS_FOR_EIGHT_RECORD_CANARY_ONLY
NO_RESULT_CACHE            STATIC_CALL_LOOP_PASS; INDEPENDENT_CASES_FAIL
ALGEBRAIC_RECOMPOSITION    PASS_WITH_ONE_CSV_COVERAGE_EXCEPTION
```

Because F10 fails, the old confidence interval and sign test are not admissible
for a corrected campaign.
