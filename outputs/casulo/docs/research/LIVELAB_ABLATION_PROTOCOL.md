# LiveLab causal ablation and profiling protocol

The frozen plan is defined in `src/casulo/livelab/ablations.py`. It contains
all nine attacks required by the Scientific Covenant: buffer reuse,
vectorization, compiler optimization, 1/2/4 workers, autograd versus verified
specialized backward, fused versus separate phases, static versus dynamic
shapes, direct versus general-IR T routes, and conventional versus semantic
scheduling.

Every variant keeps inputs, initialization, dtype, operation scope and quality
tolerance identical. Quality is judged before timing. The plan requires three
warm-ups, at least 21 paired samples, a seeded 10,000-resample paired bootstrap,
pre-registered exclusions only, the Thermal Covenant, and identical validated
power state. An unfavorable result is retained.

Profiling is bounded to the complete child process equivalent step. The frozen
counter set includes task-clock, cycles, instructions, branches, branch and
cache misses, context switches, migrations and page faults. Missing `perf`
access yields `unavailable` with every counter set to `null`; temperature and
TDP are never substituted for energy.

The current Windows host validates the plan and fail-closed representation but
cannot execute the Linux `perf`/cgroup campaign. Therefore this protocol is
implementation and preregistration evidence, not an ablation result or a
performance claim.
