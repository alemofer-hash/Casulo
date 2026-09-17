# Full FloodSurrogate TCAP worker

The full worker is implemented in `src/casulo/t/full_work_unit.py`,
`src/casulo/t/learn_native.py`, and
`src/casulo/livelab/energy_v1/full_workers.py`.

The kernel performs, inside every epoch, gradient reset, forward over 1,024
records, MSE accumulation, backward accumulation, normalization, and 81 SGD
updates. The runtime—not the runner—increments forward, backward, optimizer,
record-visit, parameter-write, and completed-epoch counters.

The TCAP embeds the general IR, graph, executable code, scientific dataset,
initialization bundle, work-unit contract, source, and the separately labelled
correctness canary. Dataset and cases are passed to the raw kernel at runtime;
the compiler cannot precompute final results.

The mechanism is a fused, static-shape, contiguous scalar kernel with no
dynamic autograd graph, tensor-dispatch loop, or per-epoch optimizer object.
This explains a workload-specific constant-factor advantage over the Eager
reference; it is not evidence of general superiority over PyTorch or Inductor.

Validation campaign:
`outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2/`.
All eleven pre-energy gates passed. The earlier `v1` attempt is retained as a
failed K-linearity attempt (`R²=0.993528` under an incorrect replicate fit).

