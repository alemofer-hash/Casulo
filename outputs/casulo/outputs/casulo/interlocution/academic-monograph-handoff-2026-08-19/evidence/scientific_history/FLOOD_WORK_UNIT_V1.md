# FloodSurrogate scientific work unit V1

## Identity

`SCIENTIFIC_WORK_UNIT` is one independent full-batch training with 1,024 real
records, eight float64 inputs, one target, one hidden layer of eight ReLU
units, one output, MSE, SGD at learning rate 0.018, and 400 epochs.

The bounded eight-record artifact is `CORRECTNESS_CANARY`, has
`scientific_eligible=false`, and is valid only for correctness, CI, loader
smoke tests, and minimal equivalence checks.

## Exact work

| Field | Required value |
|---|---:|
| records per epoch / batch size | 1,024 |
| epochs, forward epochs, backward epochs | 400 each |
| optimizer steps | 400 |
| record visits | 409,600 |
| trainable float64 parameters | 81 |
| parameter writes | 32,400 |

`parameter_writes` counts one completed SGD write for each of 81 parameters in
each epoch. It does not count gradient scratch writes.

## Dataset ABI

The binary payload is `FWDATA1`, little-endian, eight-byte aligned, with a
24-byte header followed by 8,192 float64 inputs in row-major order and 1,024
float64 targets. Its length is 73,752 bytes and SHA-256 is
`f393212f183a28a663adeb11995c5ab3ac769df7f06ded2dcfbc5e91cd31f802`.
The deterministic generator manifest hash is
`2e95b25f761d617490d30082d17a7c191356f8441e0d04555df2fbd2f4b46e94`.

The initialization bundle is `FWINIT1`. Every case contains a case ID, seed,
32-byte nonce, and 81 float64 initial parameters. The validated bundle contains
1,024 distinct cases; all nonces and initial-parameter hashes are unique.

The loader checks the TCAP ABI, exact segment set, dataset and initialization
hashes, general IR and graph hashes, dimensions, learning rate, eligibility,
and expected counters before execution. Any mismatch fails before warm-up.

## Pipeline invariant

The route is T source → AST → semantic analysis → general IR → graph → resource
contract → counter-instrumented native lowering → TCAP → loader → process →
kernel. No benchmark-only parser or hidden training route is allowed.

