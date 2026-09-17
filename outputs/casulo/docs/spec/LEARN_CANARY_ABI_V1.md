# Casulo learn numerical canary ABI 1.0

Status: normative for the bounded `FloodSurrogate.tcap` correctness canary.

This canary is an eight-record numerical correctness test for repeatable QEMU
rehearsals. It is **not** the historical 1,024-record performance campaign and
does not support a speed, energy or throughput claim.

## Segment and bounds

The TCAP read-only segment is named `canary`, is aligned to 8 bytes and has an
exact length of 1,952 bytes. All integers and IEEE-754 binary64 values are
little-endian. The v1 bounds are fixed at 8 records, 8 inputs, 8 hidden units,
1 output, 400 epochs and 81 parameters. A loader rejects any other dimension,
truncation, trailing byte, non-finite scalar or invalid positive bound before
execution.

| Offset | Type | Field |
|---:|---|---|
| 0 | byte[8] | `TCANARY\0` |
| 8 | u16 | major = 1 |
| 10 | u16 | minor = 0 |
| 12 | u32 | header bytes = 80 |
| 16 | u32 | records = 8 |
| 20 | u32 | input features = 8 |
| 24 | u32 | hidden features = 8 |
| 28 | u32 | output features = 1 |
| 32 | u32 | epochs = 400 |
| 36 | u32 | parameter count = 81 |
| 40 | f64 | learning rate = 0.018 |
| 48 | f64 | target loss = 0.08 |
| 56 | f64 | absolute comparison tolerance = 1e-9 |
| 64 | f64 | expected initial MSE |
| 72 | f64 | expected final MSE |
| 80 | f64[64] | row-major inputs |
| 592 | f64[8] | targets |
| 656 | f64[81] | initial parameters |
| 1304 | f64[81] | expected final parameters |

Parameter order is `W1[feature][hidden]`, `b1[hidden]`, `W2[hidden]`, `b2`.

## Frozen scalar order

Protocol `casulo-learn-f64-loop-order/1` uses no reduction reordering:

1. evaluate records in ascending order; features are outer and hidden units
   inner for `W1` accumulation; hidden units are ascending for the output;
2. for each epoch, zero all gradients, then process records ascending;
3. accumulate output bias, then each `W2`/`b1` gradient, then each `W1`
   gradient with feature outer and hidden inner;
4. update parameters once, in ascending flat parameter order;
5. evaluate the final MSE with the same first-step order.

The builder's literal scalar implementation and the independent audit
implementation must agree bit-for-bit on the host. Kernel output passes when
initial loss, final loss and every final parameter differ from the embedded
values by at most `1e-9`, and final loss is at most `0.08`.

For the current deterministic fixture:

- initial loss: `0.5514087300000001`;
- final loss: `0.007241680427492191`;
- canary segment SHA-256:
  `56faf993c90c58a68a35ee2469567b756bb10dcde129c391b27eb8282b117fc9`;
- complete TCAP SHA-256:
  `c5ca30051e9bb337a5e009de5083b761d24a2117ad3d5d07ff4f78fb3cc98327`.

TCAP integrity still precedes this semantic check. A segment hash failure is
`QUARANTINE`, and no embedded expectation is trusted or executed.
