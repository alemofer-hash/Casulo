# LiveLab shared workload protocol 1.0

Status: Research Preview correctness infrastructure. This document contains no
performance result and authorizes no speed, energy or superiority claim.

## Purpose

Every compared implementation must receive the same versioned workload,
synthetic bytes, initialization, precision and operation scope. An adapter that
cannot preserve that contract returns `UNAVAILABLE`; it must not silently use a
smaller graph, forward-only substitute, different optimizer or different data.

The canonical implementation lives in
`src/casulo/livelab/workloads.py`. A workload identity is
`<workload_id>@<revision>` and its SHA-256 covers the complete canonical JSON
specification. Data use the separately versioned
`casulo-livelab-synthetic-data/1.0` protocol.

## Frozen suite

| Workload | Family | Scope | Scientific role |
|---|---|---|---|
| `flood-surrogate-historical@1` | dense MLP 8x8x1 | full training step | preserves the historical declaration and original campaign generator |
| `mlp-small@1` | dense MLP | full training step | low-work crossover control |
| `mlp-medium@1` | dense MLP | full training step | intermediate arithmetic intensity |
| `mlp-large@1` | dense MLP | full training step | bounded saturation point |
| `cnn-small@1` | convolution | forward | different spatial operator family |
| `attention-compact@1` | attention | QKV, score, softmax, projection | compact Transformer-style block |
| `dynamic-length@1` | ragged control | mask, reduction, normalization | dynamic-length pressure |
| `t-unfavorable-opaque-branch@1` | scalar recurrence | ordered branch/reduction | deliberately unfavorable, no-help case |
| `flow-residual-interference@1` | scheduler interference | FLOW plus residual plus audit | latency/non-starvation experiment input |

For trainable dense workloads, “full step” means exactly `forward + loss +
backward + plain SGD update`. Campaign and smoke profiles are distinct. Smoke
profiles contain one or two small steps and are marked
`not_a_performance_campaign`; their results cannot be used as timing evidence.

The FloodSurrogate campaign profile delegates to the existing
`casulo-hydrology-surrogate/0.1` generator with data seed `20260730` and the
existing parameter initializer with model seed `260730`. Its compact smoke
fixture is a new portable correctness fixture and is not historical campaign
data.

## Portable synthetic generator

Non-historical fixtures use `splitmix64-u53/1.0`. The 64-bit state transition,
53-bit conversion and tensor iteration order are implemented directly; hashes
are golden-tested. Bias tensors are zero. Other tensors use
`uniform[-0.125, 0.125)`. Dynamic lengths are integers in `[1, max_length]`.

Changing a shape, seed, operation, tolerance, initialization or profile requires
a new workload revision and new preregistration. Updating a golden hash in place
would invalidate comparability with existing evidence.

## Adapter policy

`src/casulo/livelab/workload_adapters.py` exposes bounded executable smoke
adapters:

| Adapter | Current equivalent scope | Fail-closed behavior |
|---|---|---|
| `numpy-semantic` | all nine workloads | unavailable when NumPy or an operator is absent |
| `numpy-blas` | dense MLP and attention | unavailable for a non-BLAS formulation |
| `pytorch-eager` | dense full step | unavailable for other families; no forward-only substitution |
| `pytorch-compile` | same dense full step with `fullgraph=True` | compiler execution requires explicit opt-in; graph failure is unavailable |
| `native-c-no-t` | independent generated C dense full step | compiler opt-in; source-size cap; never reuses T-generated C |
| `historical-t-c99` | FloodSurrogate only | rejects every other topology or semantic scope |
| `t-general-ir-tcap` | FloodSurrogate TCAP canary | builds and validates the TCAP, but remains unavailable for a shared pair because its frozen 400-step canary differs from the two-step shared smoke fixture |

Toolchain adapters require `allow_toolchain=True`. This prevents unit tests from
accidentally compiling PyTorch/Inductor, C99 or Rust AOT. It is an execution
permission, not a performance gate.

Run a correctness smoke from the repository root with, for example:

```text
python livelab/workload_smoke.py numpy-semantic dynamic-length
python livelab/workload_smoke.py native-c-no-t mlp-small --allow-toolchain
```

The command emits only semantic status, hashes and provenance. It intentionally
does not collect or print elapsed time.

## Equivalence and claims

An equivalence comparison first requires both adapters to pass, identical data
hashes and identical semantic scopes. It then evaluates finite outputs against
the absolute and relative tolerances frozen in the workload spec. Mismatched
cardinality, NaN/Inf, data or scope is `FAIL`; a missing implementation or
dependency is `UNAVAILABLE`.

These smoke adapters record no wall time and no energy. Direct timing remains
subject to LiveLab preflight, thermal, power, isolation and paired-campaign
requirements. Joules remain unavailable without an advancing RAPL counter or a
validated external meter.

## Required campaign sequence

1. Freeze workload spec hash and generated data hash in the preregistration.
2. Run bounded correctness smoke against `numpy-semantic`.
3. Record every adapter as `PASS`, `FAIL` or `UNAVAILABLE`; do not omit failures.
4. Admit only semantically equivalent pairs to a performance campaign.
5. Pass thermal, power, isolation and energy gates before the first timed child.
6. Preserve all raw paired samples and report unfavorable/crossover results.
