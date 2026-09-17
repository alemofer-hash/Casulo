# Casulo LiveLab Energy Protocol V1

Status: implemented and locally validated; physical result blocked.

## Scientific boundary

The protocol recognizes four separate domains:

| Domain | Meaning | Authorized wording |
|---|---|---|
| `CPU_PACKAGE_RAPL` | Accumulated energy from one non-overlapping Linux powercap package zone | CPU package energy |
| `TOTAL_SYSTEM_WALL` | Accumulated energy from a physical meter between the wall outlet and the notebook power supply | total system energy |
| `BATTERY_DELTA` | Energy exchanged with the notebook battery | control/covariate only |
| `LOGICAL_TELEMETRY` | Scheduler operations and decisions | never energy |

Time, temperature, utilization, frequency, TDP and logical operations are not
converted to joules. Missing metrics are `unavailable`/`null`, never zero.
Hierarchical RAPL zones are recorded with their parent relation and never
summed. No MSR, power limit, firmware or power policy is written.

## Physical preflight (E0)

`casulo-energy preflight` records execution class, manufacturer/model, CPU,
microcode, firmware, topology, OS/kernel, affinity, thread policy, frequency,
power profile, AC/battery state, thermal/throttling evidence, powercap zones,
permissions, counter range and meter format.

A RAPL package source is valid only when `energy_uj` and
`max_energy_range_uj` are readable, parse as bounded integers, timestamps
advance and the counter advances during a bounded controlled load. A missing,
invalid or stationary counter blocks execution. During each measured window a
read-only monitor samples at 50 ms, computes only adjacent single-wrap deltas
and accumulates every observed wrap. Sample count, total wraps and maximum
sampling interval are preserved; a multi-wrap window is never inferred from
only two endpoints.

A wall meter must expose a physical cumulative-joule counter through a
loopback API or timestamped CSV/JSONL export. Instantaneous watts alone are
diagnostic. Mock sources are accepted only by unit tests and can never produce
a scientific sample or a physical report.

## Equivalent unit (E2)

One unit is one complete training from the same frozen dataset,
initialization, parameters, dtype/precision, seed and semantic operation scope,
including forward, loss, backward and optimizer where declared. Every unit
restarts from the same mathematical state. The equivalence gate compares loss,
parameters and predictions/numeric outputs against frozen absolute and
relative tolerances before any energy window.

The priority comparisons are registered independently:

1. T through semantic analysis, general IR, graph and TCAP;
2. PyTorch Eager full step;
3. `torch.compile` full step, including optimizer;
4. independent native C;
5. semantic scheduler versus FIFO/conventional policy under interference.

Initialization, compilation, three warm-ups, stationary execution and shutdown
are separate phases. Compilation-included and compilation-excluded campaigns
are distinct metrics. No compile cost may be hidden.

## Calibration and amplification (E3)

Calibration runs three warm-ups outside samples and derives a separate integer
`K` per implementation. `K` repeats complete independent units; it does not
change epochs, batch, data or math. Target windows are at least 10 seconds and
preferably 30 seconds for RAPL, and 60–120 seconds for the wall meter. Values
of `K` and the deterministic AB/BA schedule are frozen before definitive
results. Runner overhead and incremental-over-idle energy are secondary
measurements and never replace raw energy.

## Battery and thermal guards (E4)

AC must remain connected. Wall samples are rejected on battery-state
transition or when the absolute battery-energy change exceeds:

`max(2 × sensor resolution, 1% × wall energy)`.

If battery energy is unobservable, the result is
`WALL_UNCONTROLLED_BATTERY` and cannot support a definitive total-system
claim. The thermal covenant remains 55 °C, requires advancing evidence, rejects
drift above 3 °C within a paired window and rejects any detected throttling.
Odor, electrical instability, frozen telemetry or isolation failure requires
immediate stop.

## Confirmatory paired campaign (E5)

- three warm-ups outside measurements;
- 21 valid pairs per session;
- three independent sessions;
- seeded, balanced AB/BA order frozen before results;
- identical threads, affinity, power and thermal gates;
- no post-observation outlier removal;
- immutable append-only raw JSONL with idempotent resume;
- automatic rejection reasons preserved separately.

The primary ratio is `J_candidate / J_baseline`. Advantage against one named
baseline requires equivalence PASS, median ratio below 1, paired bootstrap
95% CI entirely below 1, consistent direction in all sessions, and no thermal
or battery violation. The report includes an exact sign test. Improvement of
at least 10% is called material; a smaller significant effect is called small.
Negative results are retained.

## Casulo Native (E6)

QEMU may validate schemas, missing-source behavior, overflow, persistence and
reports only. It cannot measure energy. Casulo Native versus Linux requires the
same physical hardware and an external wall meter. Native RAPL remains disabled
until a processor allowlist, read-only MSR implementation, unit calculation,
wraparound handling and cross-validation against Linux RAPL and the meter all
pass.

## Commands

Repository-local CLI equivalent:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
python livelab/casulo_energy.py preflight --campaign-id <id> --campaign-dir energy/<id> --domain CPU_PACKAGE_RAPL
python livelab/casulo_energy.py calibrate --campaign-id <id> --campaign-dir energy/<id> --commands <commands.json>
python livelab/casulo_energy.py smoke --campaign-id <id> --campaign-dir energy/<id> --commands <commands.json>
python livelab/casulo_energy.py run --campaign-id <id> --campaign-dir energy/<id> --commands <commands.json>
python livelab/casulo_energy.py analyze --campaign-id <id> --campaign-dir energy/<id>
python livelab/casulo_energy.py report --campaign-id <id> --campaign-dir energy/<id>
```

The local wrapper avoids changing `pyproject.toml`, which is part of the frozen
TCAP compiler provenance. It is semantically the requested `casulo-energy` CLI.
