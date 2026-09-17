# Full-worker K linearity

K was executed in ascending and descending order for `1, 2, 5, 10, 20, 50,
100`. Every observation retained exact receipts and counters.

The first analysis incorrectly treated direction replicates as independent
regression x-values and returned TCAP `R²=0.993528`. It remains sealed as a
failed attempt. A regression test fixed the estimator before the new campaign:
each K is the regression unit, and the median of all preregistered direction
replicates is its central time. No observation was removed.

| Implementation | Slope per full training | Intercept | R² | Gate |
|---|---:|---:|---:|---|
| T/general IR/TCAP full | 32.375120 ms | -38.547668 ms | 0.99801055 | PASS |
| PyTorch Eager full step | 274.936526 ms | 1,974.232633 ms | 0.99870418 | PASS |

The negative TCAP intercept reflects timing noise in short K values and is not
used as physical negative overhead. The slope is the admissible steady-regime
per-training estimate. Its ratio is approximately 8.49× in time for this host
and workload.

