# LiveLab paired-campaign protocol v1

This protocol defines when a Casulo/T versus PyTorch/Inductor campaign may
start. Its purpose is reproducible comparison and hardware protection, not a
presumption that either implementation wins.

## Fail-closed preflight

Every required capability must be directly observed as available. The default
campaign requires process affinity, sealed numerical thread pools, cgroup v2
cpuset and CPU controls, an advancing thermal stream, stable AC power and CPU
policy, operator confirmation that no abnormal odor is present, and a validated
external meter with cumulative joules. An absent, stale, invalid or
permission-blocked input blocks the run. Zero is never substituted for missing
energy, and an unavailable control is never described as applied.

The preflight result is persisted even on failure. A blocked result must have
`status=blocked_before_start`, `workload_invocations=0`, `trials=[]`, no
aggregates and an empty CSV containing only its header.

## Pairing and safety

Measured pairs alternate order: AB, BA, AB, BA. The executor reevaluates all
safety gates immediately before each warm-up and each trial. Exceeding the
configured temperature limit aborts the campaign at the first observed hot
trial. A per-trial maximum duration is mandatory for the executor. Thermal
cooldown policy remains outside the timed region.

Both implementations receive equivalent fixed inputs and must emit the same
canonical output digest within the test's declared precision contract. A digest
mismatch aborts the campaign and suppresses comparative aggregates.

The bounded executor starts a supervisor which waits before launching workload
code. LiveLab applies and reads back CPU affinity, seals numerical-library
thread variables, and optionally attaches the supervisor to a newly-created
cgroup v2 child before releasing it. Descendants inherit these controls. Each
trial has a wall timeout, thermal polling throughout execution, cumulative
energy snapshots, an invariant power-state signature, transactional cgroup
cleanup, process-tree termination and a zero-supervisor check. A blocked
preflight creates no child process at all.

## Reports and claims

Each campaign writes canonical JSON, trial-level CSV and a readable Markdown
report. The primary estimator is the median of the within-pair
baseline/candidate ratios, not a ratio of independently aggregated medians.
Strict inference requires at least 21 complete main pairs and reports a seeded
paired bootstrap 95% interval plus a two-sided exact sign test. Bootstrap
resampling keeps each AB/BA pair intact. Ties are omitted only from the sign
test denominator.

Compile time remains a separate field and is also reported under an explicitly
declared amortization count. Execution phase timings remain trial-level data.
An exclusion may affect analysis only when its reason code was preregistered in
the campaign specification; an unregistered reason aborts the campaign. These
statistics do not claim hardware-wide energy from RAPL, equivalence from
runtime alone, or uniform superiority from a single workload.

`uclamp`, `perf` and `sched_ext` use explicit controller/collector interfaces.
On Windows they report `unavailable`; on Linux discovery alone reports
`not_applied`, never a successful control. Actual application must have a host
adapter and observable read-back.

The Linux campaign executor, thermal adapter, external-meter adapter and power
state sampler must be configured and validated on the actual experiment host
before the first non-dry run. The Windows preflight is expected to fail while
Linux-only controls and trusted hardware telemetry are unavailable.

## Synthetic reproduction

The command below exercises reporting and statistical mathematics only. It is
not performance evidence and every output marks its source as synthetic:

```powershell
$env:PYTHONPATH = "src"
python livelab/generate_fake_statistics.py --output evidence/casulo-os-rp01/g5/deterministic-statistics
```

The generated JSON contains the raw trials and estimator metadata (seed,
resample count and exact-test counts); CSV contains one row per trial; Markdown
is a readable rendering. No synthetic value may be reused as a product claim.
