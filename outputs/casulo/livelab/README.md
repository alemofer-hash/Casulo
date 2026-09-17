# Casulo LiveLab

LiveLab is the Linux-first experimental instrument for capability discovery, process controls, hardware counters and baseline comparisons. It is not Casulo Native.

The implementation provides a truthful capability matrix, a deterministic
userspace semantic policy and fail-closed experimental controls. On Windows,
Linux-specific controls report `unavailable` with `null` values. No cgroup,
RAPL, perf or sched_ext result is inferred.

Implemented controls:

- rollover-aware RAPL deltas from `energy_uj` and `max_energy_range_uj`;
- external meter validation requiring stable identity, monotonic timestamps and
  an advancing cumulative-joule counter;
- transactional cgroup v2 child setup for cpuset, `cpu.weight` and `cpu.max`,
  with PID return and exact-child cleanup;
- common numerical-library thread sealing, plus verified PyTorch intra/inter-op
  limits when PyTorch is supplied;
- a functional PyTorch baseline whose one step contains forward, loss,
  backward and plain SGD update. Its compiled form requests
  `torch.compile(fullgraph=True)` and reports unavailable instead of silently
  falling back to an incomplete baseline.

RAPL cannot prove whole-system energy. An external meter is accepted only after
its cumulative-energy stream passes validation; instantaneous watts are never
integrated implicitly. The RAPL sampler assumes at most one counter rollover
between two reads, so protocols must bound their sampling interval.

The paired-campaign harness alternates AB/BA order, checks safety immediately
before every warm-up and measured trial, and accepts a pair only when both
output SHA-256 digests match. A missing thermal stream, operator odor check,
stable AC power state, external cumulative-energy meter or requested cgroup
control produces `blocked_before_start`, an empty trials CSV and no workload
invocation. `livelab/preflight_campaign.py` is a preflight-only command: it
cannot start PyTorch or Casulo work.

Energy Protocol V1 is exposed without changing the frozen TCAP compiler
provenance:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
python livelab/casulo_energy.py --help
```

Its implementation is under `src/casulo/livelab/energy_v1/`; the full protocol
and current physical block are documented in
`docs/research/ENERGY_PROTOCOL_V1.md` and `ENERGY_FINAL_REPORT.md`.
