# HWiNFO thermal recovery campaign

Scientific state: `BLOCKED_HWINFO_POLLING_NOT_CHANGED`

## R1 result

- Median interval: `2.000500 s`
- P95 interval: `2.005350 s`
- Required median: `<= 0.550 s`
- Required P95: `<= 0.750 s`
- New samples: `15`
- Workload executions: `0`

The active logger is still near its previous polling period. `Global Polling
Period` must be configured to `500 ms` before any thermal probe or definitive
window. The prior blocked campaign and the source CSV remain unchanged.

No joules per training, paired ratio, confidence interval, or energy advantage
is reported. `TOTAL_SYSTEM_WALL` and `CASULO_NATIVE_ENERGY` remain
`BLOCKED_PHYSICAL_INSTRUMENT`.
