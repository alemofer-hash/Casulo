# TCAP versus PyTorch Eager full-worker equivalence

The oracle uses PyTorch Eager, float64, one thread, affinity `[4]`, full batch,
MSE, `torch.optim.SGD`, learning rate 0.018, the same 1,024-record dataset, and
the identical sequence of initializations.

Across every ascending and descending K comparison:

| Quantity | Maximum absolute difference | Frozen tolerance |
|---|---:|---:|
| 81 final parameters | 4.440892098500626e-16 | 1e-9 |
| 1,024 final predictions | 1.7763568394002505e-15 | 1e-9 |
| final loss | 1.1102230246251565e-16 | 1e-9 |

All counters matched exactly: 400 forward, backward, optimizer, and completed
epochs; 409,600 record visits; and 32,400 parameter writes per training. No
NaN/Inf, result cache, receipt replay, or duplicated case was accepted.

