# G5 energy final report

Date: 2026-08-07  
Scientific terminal state: `BLOCKED_PHYSICAL_INSTRUMENT`

## Latest recovery state: 500 ms passed, 250 ms fallback pending

The live HWiNFO logger was reconfigured and a clean new segment passed R1 at
`0.500 s` median and `0.5071 s` p95. An initial calibration attempt was sealed
without candidate workload after discovering that the physical guard reparsed
the entire growing CSV on every poll. The replacement `bounded-live-tail-v1`
reduced measured guard-read latency from `284.71 ms` to `10.53 ms` per call
(`27.03x`) while preserving full-snapshot parsing for scientific integration.
This diagnostic latency result is not energy evidence.

Campaign `2026-08-07-g5-hwinfo-thermal-recovery-03` then passed polling and
collected a valid 60.013-second idle window: 122 samples, `9.858943313 W`, and
median CPU temperature `51 C`. The derived frozen start threshold was `54 C`.
Before equivalence or any TCAP/Eager training, the instantaneous HWiNFO
temperature reached `75 C`; the guard aborted with no throttling, zero workload
executions, no frozen K, and `0/21` pairs. This 500-ms branch is sealed and does
not authorize an energy conclusion.

The software fallback is complete and tested: a separate 250-ms protocol,
median polling gate `<=0.300 s`, minimum 20-second/60-sample qualification,
10/20-second probes, per-implementation K freeze, three out-of-sample warmups,
transactional AB/BA pairs, pre/post-pair equivalence, bootstrap/sign-test
analysis, report, segment extraction, and hashes. The remaining external action
is to set HWiNFO `Global Polling Period` to `250 ms`; no frequency may change
inside that new campaign.

Prepared preflight command:

```powershell
casulo-energy hwinfo recover --csv "C:/Users/guimo/Documents/Codex/2026-07-28/ex/outputs/casulo/benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV" --campaign-id 2026-08-07-g5-hwinfo-thermal-recovery-250ms --polling-ms 250 --phase preflight
```

## Thermal-recovery polling gate

Campaign `2026-08-07-g5-hwinfo-thermal-recovery` was created without
modifying the earlier blocked campaign. R1 used only rows appended after the
new formal timestamp and byte offset. Fifteen new samples produced a median
interval of `2.000500 s`, p95 `2.005350 s`, minimum `1.991 s`, and maximum
`2.006 s`. Timestamps were strictly increasing and package-power values were
finite and nonnegative.

The required limits were median `<= 0.550 s` and p95 `<= 0.750 s`.
Consequently the terminal state is
`BLOCKED_HWINFO_POLLING_NOT_CHANGED`. No idle/load probe, TCAP execution,
PyTorch execution, K freeze, warm-up, or definitive pair was started. The
single external action is to configure HWiNFO `Global Polling Period` to
`500 ms` while continuing to log the same sensor.

## HWiNFO Windows campaign update

Campaign `2026-08-07-g5-hwinfo-tcap-vs-eager` added a validated, live
HWiNFO CSV source for the literal field `Potência total da CPU [W]`. The file
was UTF-8 BOM, comma-delimited, decimal-point encoded, advancing at a median
interval of approximately 2.001 seconds, and showed no timestamp regression.
This authorizes only the scope "HWiNFO-reported CPU package energy on
bare-metal Windows".

The pre-energy mathematical gate passed for the real general T pipeline/TCAP
and PyTorch Eager canary: 400 epochs, float64, identical dataset and initial
parameters, maximum final-parameter difference `2.220446049250313e-16`, and
maximum prediction difference zero.

The physical campaign did not pass calibration. Three independent 120-second
idle windows were valid, but averaged 7.0424 W, 5.0168 W, and 3.8877 W. During
controlled-load calibration, rejected attempts reached 81 °C with HWiNFO
thermal throttling and later 76 °C after short probes. The 75 °C warning gate
therefore stopped execution before K was frozen and before any definitive
pair. Valid pairs are `0/21`; joules per training, paired ratio, confidence
interval, and sign test are unavailable. No energy advantage is claimed.

Authoritative local evidence is sealed under
`energy/2026-08-07-g5-hwinfo-tcap-vs-eager/`. `TOTAL_SYSTEM_WALL` and
`CASULO_NATIVE_ENERGY` remain `BLOCKED_PHYSICAL_INSTRUMENT`.

## Outcome

E0–E6 instrumentation is implemented and locally validated. The physical
campaign did not start because this Windows host exposes neither a valid Linux
CPU-package RAPL counter nor a physical cumulative-joule wall meter, and its
battery telemetry lacks energy/resolution fields required to control a wall
measurement.

The complete command sequence was executed against campaign
`2026-08-07-g5-energy-final`:

| Stage | Result | Workload invocations | Joules |
|---|---|---:|---:|
| preflight | `BLOCKED_PHYSICAL_INSTRUMENT` | 0 | unavailable |
| calibrate | `BLOCKED_PHYSICAL_INSTRUMENT` | 0 | unavailable |
| smoke | `BLOCKED_PHYSICAL_INSTRUMENT` | 0 | unavailable |
| run | `BLOCKED_PHYSICAL_INSTRUMENT` | 0 | unavailable |
| analyze/report | `BLOCKED_PHYSICAL_INSTRUMENT` | 0 | null |

The sealed campaign manifest initially verified ten artifacts. The definitive
manifest and `SHA256SUMS` in the campaign directory are authoritative after
release packaging and final validation.

## What is proved

- unavailable energy cannot become zero;
- mocks cannot become physical measurements;
- Windows/WSL/VM/QEMU cannot silently become RAPL evidence;
- hierarchical RAPL zones cannot be double-counted;
- multiple RAPL wraps in a long window are accumulated from periodic adjacent
  samples rather than guessed from two endpoints;
- battery, thermal, AC, equivalence and counter-advance failures reject a sample;
- interruption is resumable without duplicate raw samples;
- 3 × 21 paired analysis and its statistical decision are deterministic and tested;
- compilation-included/excluded scopes remain separate;
- raw evidence is content-addressed and locally sealed.

## What is not proved

- no CPU-package or total-system energy advantage;
- no energy comparison against PyTorch Eager, `torch.compile`, Inductor or C;
- no amortization point;
- no Casulo Native versus Linux energy result;
- no new speed result;
- no attribution of the historical `8.957846×` Eager result to Casulo SO.

## Single remaining physical action

Connect a calibrated cumulative-energy wattmeter with a local USB/API stream at
at least 1 Hz **between the wall outlet and the notebook power supply**, expose
its samples at `http://127.0.0.1:8787/samples`, boot a bare-metal Linux Live
environment without installing it or changing the internal disk, leave AC
connected and battery stable, reserve approximately 4–8 hours, and execute this
single exact chain:

```bash
cd /path/to/casulo
export PYTHONPATH="$PWD/src"
ID=g5-physical-final
DIR=energy/$ID
COMMANDS=energy/commands/flood_canary_tcap_vs_eager.json
python livelab/casulo_energy.py preflight --campaign-id "$ID" --campaign-dir "$DIR" --domain TOTAL_SYSTEM_WALL --wall-meter-api http://127.0.0.1:8787/samples && \
python livelab/casulo_energy.py calibrate --campaign-id "$ID" --campaign-dir "$DIR" --commands "$COMMANDS" && \
python livelab/casulo_energy.py smoke --campaign-id "$ID" --campaign-dir "$DIR" --commands "$COMMANDS" && \
python livelab/casulo_energy.py run --campaign-id "$ID" --campaign-dir "$DIR" --commands "$COMMANDS" && \
python livelab/casulo_energy.py analyze --campaign-id "$ID" --campaign-dir "$DIR" && \
python livelab/casulo_energy.py report --campaign-id "$ID" --campaign-dir "$DIR"
```

Expected first gate artifact:
`energy/g5-physical-final/capabilities.json` with
`TOTAL_SYSTEM_WALL: ready`, an advancing physical counter, observable battery
energy/resolution, trusted thermal evidence and `ready: true`. Expected final
artifact: `energy/g5-physical-final/report.md`. Shell `&&` guarantees that no
later stage starts if the physical gate fails.

## HWiNFO Windows thermal-recovery campaign (2026-08-07)

The sealed campaign
`energy/2026-08-07-g5-hwinfo-thermal-recovery-250ms-90c-start70-kfreeze-fixed/`
completed 21 valid AB/BA pairs after 10 definitive pair rejections. One
additional rejected calibration artifact records a short qualification retry.
The active source was the literal HWiNFO field `Potência total da CPU [W]`,
with 0.255 s median and 0.267 s p95 polling intervals.

Numerical equivalence passed before and after every accepted pair. Median
HWiNFO-reported package energy per independent 400-epoch training was
0.0038897192190195237 J for T/TCAP and 2.5318306505471764 J for PyTorch Eager.
The paired TCAP/Eager median ratio was 0.0015239981590574325; its seeded 95%
bootstrap interval was [0.0014016660419851176, 0.0016165606798826668], with
21/21 favorable pairs and two-sided exact sign-test p=9.5367431640625e-07.

This is **not a PASS**. The campaign terminated as
`INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS` because median peak-temperature
asymmetry was 7.0 °C, exceeding the frozen 3.0 °C parity limit. Accepted-window
maxima reached 78 °C for TCAP and 74 °C for Eager, without instantaneous
throttling in accepted windows. No outlier was removed. The result cannot be
used to claim CPU-package energy advantage until a separately preregistered
campaign resolves thermal parity without changing the current evidence.

`TOTAL_SYSTEM_WALL` and `CASULO_NATIVE_ENERGY` remain
`BLOCKED_PHYSICAL_INSTRUMENT`. The campaign does not authorize claims about
Inductor, GPU/TPU, datacenters, other hosts or total-machine energy.

## Forensic errata — 2026-08-08

The 2026-08-07 HWiNFO result is now classified
`INVALIDATED_INCOMPLETE_WORK_UNIT`. The TCAP and Eager workers both executed
the eight-record bounded correctness canary, whose release evidence explicitly
states `not_a_performance_campaign=true`, rather than the declared 1,024-record
training. A wrapper call therefore visited 3,200 records across 400 epochs,
not 409,600. The reported joules-per-training values, paired interval and sign
test may not be reused as evidence for the full FloodSurrogate work unit.

The original campaign remains immutable and retains its historical
`INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS` report. The errata and forensic
inventory are additive. A regression now makes every new scientific energy
initializer reject this bounded canary.

## Corrected full-worker attempt — 2026-08-08

The 1,024-record × 400-epoch worker passed contract, dataset, general pipeline,
internal receipts, exact counters, unique cases, K linearity, three-clock sync,
TCAP/Eager equivalence, cache exclusion, canary separation, and historical
sanity gates.

The new HWiNFO campaign then stopped as `BLOCKED_THERMAL_OR_SENSOR` after an
instantaneous throttling indication during calibration cooldown. No definitive
pair ran. The standalone TCAP calibration is preserved but cannot establish an
energy advantage. See `docs/research/FULL_WORKER_ENERGY_REPORT.md`.

## Definitive full-worker thermal investigation — 2026-08-08

The 68 °C indication was not a parser error, a latched maximum or a power-limit
flag. Three instantaneous HWiNFO thermal fields changed to `Sim` at the exact
sample and returned to `Não` immediately afterwards. It is classified
`GENUINE_INSTANTANEOUS_THERMAL_THROTTLE`.

A fresh 20-minute interval with no TCAP/Eager workload then failed before
Control A. Across 4,790 samples, the host ranged from 46 to 77 °C and emitted
four instantaneous core/P-core 1 throttling samples. The longest preregistered
±1 °C stable interval was 7.293 seconds versus the required 30 seconds.

The terminal state is `BLOCKED_PHYSICAL_COOLING_REQUIRED`: `K_TCAP` and
`K_Eager` were not calibrated, 0/21 pairs ran, and comparative joules remain
unavailable. See `docs/research/FULL_WORKER_ENERGY_FINAL.md` and
`outputs/casulo/energy/2026-08-08-g5-full-worker-energy-definitive-04/`.
