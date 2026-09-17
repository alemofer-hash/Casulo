# FloodSurrogate Work Unit Specification V1

## Normative unit

One scientific FloodSurrogate training is exactly one independent, synchronous
execution with:

- 1,024 training records and eight binary64 inputs per record;
- one dense 8 x 8 hidden layer, eight biases, ReLU, one dense 8 x 1 output and one output bias;
- full-batch mean squared error;
- binary64 SGD with learning rate `0.018`;
- independently frozen initial parameters, dataset seed and nonce;
- 400 complete epochs;
- one complete forward, backward and 81-parameter SGD update per epoch;
- final loss, 81 final parameters and 1,024 predictions materialized and verified.

The required receipt counters for one unit are:

```text
epochs_completed       = 400
optimizer_steps        = 400
records_visited        = 409600
forward_epochs         = 400
backward_epochs        = 400
parameter_writes       = 32400
```

`records_visited` counts training records participating in forward/backward.
The two diagnostic loss evaluations before and after training are recorded
separately and do not replace any epoch.

## Prohibited substitutions

A unit is not a dispatch, wrapper call, epoch, batch fragment, correctness
canary, cached result, receipt replay or copied final output. In particular, the
eight-record TCAP segment named `canary` is a bounded correctness fixture. Its
own release evidence says `not_a_performance_campaign=true`; it is exactly
1/128 of the required record count and cannot be normalized as a scientific
training.

For `K` independent units the runtime must emit exactly `K` receipts and prove:

```text
epochs_completed       = 400 * K
optimizer_steps        = 400 * K
records_visited        = 409600 * K
parameter_writes       = 32400 * K
```

Every receipt contains a unique nonce, seed, final loss, parameter hash,
prediction hash and chain hash. Preparation, compilation and warm-up are timed
separately. The measured interval ends only after synchronous completion,
receipt flush and child-process confirmation.

## Conservative operation accounting

The scalar IR contains, per record and epoch, 64 first-layer multiply-adds,
eight output multiply-adds, gradient propagation for eight hidden units and 64
first-layer gradient multiply-adds. It also performs 81 SGD parameter updates
per epoch. Counting multiply and add as separate arithmetic operator events
gives well over 100 million scalar operator events per 1,024-record, 400-epoch
unit before diagnostic evaluations. This is a plausibility bound, not a claim
about retired hardware instructions or FLOPs after vectorization.

## Gate

An energy or speed report may use `J/training` or `s/training` only when the
receipt counters above are observed inside the executing implementation. A
wrapper-reported `K` alone is insufficient.
