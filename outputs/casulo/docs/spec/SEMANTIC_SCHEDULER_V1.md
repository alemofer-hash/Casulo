# Semantic Scheduler v1

Status: host functional reference. This document does not claim a complete
kernel port, wall-clock speedup, energy advantage, or S6.

## Purpose and boundary

The v1 policy makes semantic traffic classes explicit and auditable. It is a
deterministic reference vector for the later kernel implementation. A tick is a
logical unit of budget consumption, not a unit of elapsed time. Scheduler
overhead is reported only as deterministic operation counts; unavailable time
or joules are never replaced with zero.

The required queues are:

1. `FLOW`
2. `SYSTEM`
3. `ATTRACTOR_RETRY`
4. `ATTRACTOR_LOW_CONFIDENCE`
5. `ATTRACTOR_AUDIT`
6. `QUARANTINE`

## Admission invariants

Integrity, permissions, declared quality and isolation are independent hard
gates. A failure in any gate moves the task to `QUARANTINE` before ranking.
Explicitly requested quarantine has the same result. Quarantined work is never
inserted in a runnable queue and cannot be selected by either the semantic
policy or its conventional comparator.

Each admission records the requested class, admitted class, deterministic
sequence and reason. Ranking is forbidden from overriding a gate, including to
meet a deadline.

## Bounded task contract

| Field | Bounds | Meaning |
|---|---:|---|
| `budget_ticks` | 1 through 1,000,000 | Exact number of one-tick dispatches required |
| `priority` | -20 through 20 | Higher value wins only after class and deadline rules |
| `deadline_tick` | 1 through 1,000,000,000 or absent | Absolute logical completion deadline |

Every dispatch consumes exactly one budget tick. Completion occurs at zero.
`deadline_missed` is evidence, not a mechanism for silently changing quality,
permissions, isolation, or budget.

## Semantic selection

The algorithm is deterministic:

1. If an audit task is pending at a configured `audit_interval` boundary,
   dispatch one audit tick with reason `periodic_non_starvation`.
2. Otherwise choose the first non-empty class in this order: `FLOW`, `SYSTEM`,
   `ATTRACTOR_RETRY`, `ATTRACTOR_LOW_CONFIDENCE`, `ATTRACTOR_AUDIT`.
3. Within that class choose earliest deadline, then highest priority, then
   original FIFO sequence. An absent deadline sorts after bounded deadlines.
4. Consume one tick, record the complete decision, and return unfinished work
   to its class.

For a continuously pending audit queue under continuously runnable FLOW, the
reference invariant is a maximum audit service gap no larger than
`audit_interval`. For a finite admitted task set, all bounded work eventually
completes. This is not a liveness claim for an unbounded adversarial arrival
stream.

## Conventional comparator

`conventional_fifo_round_robin_v1` is deliberately simple and deterministic.
It applies the identical hard gates and then places every admitted task in one
flat FIFO queue. Each task receives one tick and unfinished work returns to the
tail. It ignores semantic class, deadline and priority for selection. Its role
is a controlled policy comparator, not a representation of Linux, Windows,
PyTorch, or Inductor.

## Pre-registered causal scenarios

The task multiset, enqueue order, one-tick dispatch cost, hard gates and maximum
ticks are frozen before both policies run. The only causal variable is the
scheduler policy.

`controlled_interference_help` places SYSTEM and RETRY interference before two
FLOW tasks and also exercises LOW_CONFIDENCE and AUDIT. Its pre-registered
expectation is lower FLOW p95-style completion latency under the semantic
policy.

`controlled_no_help` contains only identical one-tick FLOW tasks. Its
pre-registered expectation is equality. This negative control prevents the
reference from implying that semantic classification must always help.

The p95-style metric is nearest-rank over integer completion ticks measured from
the common enqueue origin tick zero. It is not a time measurement.

## Evidence contract

The generator is:

```text
python -m casulo.livelab.scheduler_evidence --output evidence/casulo-os-rp01/g4/host-reference
```

It emits:

- `scheduler-functional-evidence.json`: scenarios, traces, metrics, hard-gate
  proof, non-starvation proof and explicit excluded claims;
- `scheduler-events.csv`: one row per deterministic dispatch;
- `scheduler-functional-report.md`: human-readable summary.

The overhead proxy counts admission gate checks, selection checks and
dispatches. It exists to compare implementation work mechanically without
mislabeling those counts as runtime or energy.

## Kernel port conformance markers

The later kernel port must emit the following serial markers before it can be
called conformant:

```text
CASULO_G4_POLICY_ID=semantic_v1
CASULO_G4_HARD_GATES=integrity,permissions,quality,isolation
CASULO_G4_AUDIT_BOUND_TICKS=<configured_interval>
CASULO_G4_QUARANTINE_DISPATCHES=0
CASULO_G4_REFERENCE_VECTOR_SHA256=<digest>
```

The kernel test must also replay the host reference vector and match task id,
class, tick, decision, remaining budget, deadline state and quarantine outcome.
Printing markers without the trace comparison is insufficient. Until that port
and replay exist, G4 remains a host reference and not a kernel scheduler claim.

## Objective function boundary

The future objective
`alpha*time + beta*joules + gamma*deadline_miss + delta*quality_loss` may rank
only candidates that already satisfy hard constraints. Unknown energy remains
`null`/unavailable. Quality loss must be declared and measured; it cannot be
inferred from scheduler class or assigned a convenient value.
