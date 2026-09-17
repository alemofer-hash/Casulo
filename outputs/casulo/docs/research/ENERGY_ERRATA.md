# Energy Errata — 2026-08-08

## Affected campaign

`2026-08-07-g5-hwinfo-thermal-recovery-250ms-90c-start70-kfreeze-fixed`

The original directory, raw data, hashes and terminal state remain immutable.

## Invalidated interpretation

The following values must not be described as energy per complete
FloodSurrogate training:

```text
TCAP                  0.0038897192190195237 J
PyTorch Eager         2.5318306505471764 J
TCAP/Eager            0.0015239981590574325
bootstrap CI95        [0.0014016660419851176, 0.0016165606798826668]
```

They normalize energy by repeated executions of an eight-record correctness
canary. The required work unit contains 1,024 records. Statistical certainty
does not repair a semantically wrong denominator.

## Cause and affected versions

The HWiNFO campaign runner accepted `release/FloodSurrogate.tcap` without
checking the canary scope already recorded in `FloodSurrogate.evidence.json`.
The affected persistent-worker protocol is
`casulo-hwinfo-persistent-worker/1.0` as used by the 2026-08-07 campaigns.

## Fix

Campaign initialization now rejects the bounded canary as a scientific energy
unit. Regression coverage proves the old artifact cannot start another energy
campaign. A corrected campaign requires the full receipt/counter gates from
`WORK_UNIT_SPEC_V1.md` and receives a new identity.

## Scientific state

`INVALIDATED_INCOMPLETE_WORK_UNIT`

This errata does not invalidate the historical 1,024-record C99 versus PyTorch
timing result. It invalidates only the direct interpretation and comparison of
the eight-record energy campaign.
