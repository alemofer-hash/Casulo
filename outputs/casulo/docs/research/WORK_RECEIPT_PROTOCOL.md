# Work receipt protocol

Each completed case emits `casulo-work-receipt/1.0` after the kernel has
finished, parameters and predictions are available, and the result file has
been persisted.

The receipt binds the work-unit ID, case ID, nonce, seed, dataset and initial
parameter hashes, exact runtime counters, final loss, semantic parameter and
prediction hashes, and a counter hash. Float outputs are quantized only for the
cross-implementation semantic hash at the frozen absolute tolerance `1e-9`;
raw float64 hashes remain recorded separately.

Receipt hash:

`R_i = SHA256(canonical_json(receipt_core_i))`

Chain hash:

`H_i = SHA256(H_(i-1) || R_i)`, with `H_0` equal to 32 zero bytes.

For K cases, exactly K receipts and K distinct case IDs are required. Aggregate
counters must equal `400K` epochs and optimizer steps, `409600K` record visits,
and `32400K` parameter writes. Missing, duplicate, reordered, incomplete, or
counter-inconsistent receipts reject the run.

For the descending K=100 TCAP validation run, the aggregate chain is
`63146370481c9dbc672b39a5026c53b2f7b282c5b8d17449e6a7d4ad8ef0076f`.

