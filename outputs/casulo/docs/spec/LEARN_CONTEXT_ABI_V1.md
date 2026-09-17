# Casulo learn context ABI 0.1

Status: Research Preview, frozen for `FloodSurrogate.tcap` 0.1.

The native `learn` backend consumes `crisalida-ir/0.2` and
`metamorfose-graph/0.2`; it does not consume the historical training parser.
The historical parser is invoked afterwards only as a fail-closed equivalence
oracle. The trace is:

```text
T -> AST -> Larva analysis -> Crisalida IR -> Metamorfose graph
  -> bounded native plan -> freestanding x86_64 payload -> TCAP v1
```

## Target and calling convention

- TCAP target: `x86_64-casulo-none`.
- ABI: `casulo-learn-context-sysv64/0.1`.
- Entry symbol in the linked ELF: `casulo_learn_entry`.
- Entry offset in the extracted raw code segment: zero.
- Calling convention: x86-64 System V; `RDI` points to `LearnContext` and the
  signed 32-bit status is returned in `EAX`.
- The raw payload is position independent and the final ELF must contain zero
  relocations. The ELF is build evidence only and is not placed in the TCAP.
- RP0.1 freezes native floating-point execution as SSE/SSE2 hard-float while
  every `f64` ABI value remains in caller-owned memory. The builder rejects
  GOT/PLT sections or references, undefined symbols, indirect control
  transfers and references into the unmapped low page.

`LearnContext` is laid out with `repr(C)`:

| Offset | x86-64 type | Field |
|---:|---|---|
| 0 | `const f64*` | normalized row-major inputs |
| 8 | `const f64*` | targets |
| 16 | `f64*` | mutable parameters |
| 24 | `f64*` | caller-owned gradient arena |
| 32 | `usize` | records |
| 40 | `usize` | epochs |
| 48 | `f64` | learning rate |
| 56 | `f64*` | initial loss output |
| 64 | `f64*` | final loss output |

Total size is 72 bytes on x86-64. The current backend binds epochs and learning
rate to the T contract, caps records at 4096, uses one thread, float64,
full-batch MSE and SGD, and requires caller-owned memory. It performs no
allocation, I/O or syscall.

## Status codes

| Code | Meaning |
|---:|---|
| 0 | training completed |
| -1 | null context |
| -2 | null required buffer/output pointer |
| -3 | record count outside `1..=4096` |
| -4 | epochs or learning rate differs from the compiled contract |

Any loader integrity, resource or permission failure happens before entry and
routes to `QUARANTINE`; these are not payload status codes.

## Build and audit

```powershell
python -m casulo.t.cli tcap-build `
  examples/t/flood_surrogate_training.t `
  --output release
```

The builder uses pinned `nightly-2026-02-01`, emits a freestanding object,
links an ELF with a fixed entry section, verifies no relocations, extracts a
raw binary, packages source/IR/graph/plan/code hashes, parses the final TCAP,
and proves that a one-byte segment corruption is rejected.

The build gate also executes the exact raw bytes at a Windows-selected dynamic
address through a compiler-generated `sysv64` boundary. It must reproduce the
embedded eight-record canary within `1e-9`; this is a position-independence and
correctness check, not a performance measurement. Hosts without this harness
must report the runtime audit as unavailable rather than claiming it passed.

The host build does not prove isolated kernel execution, numerical equivalence
inside Casulo SO, thermal behavior, energy or performance. Those fields remain
`NOT_RUN`, `BLOCKED_KERNEL_EXECUTION` or `unavailable` until their respective
gates execute.

## Bounded correctness canary

`FloodSurrogate.tcap` also carries the read-only binary `canary` segment
specified by `LEARN_CANARY_ABI_V1.md`. It supplies 8-feature inputs, targets,
initial parameters, the frozen epoch/rate contract and independently audited
expected outputs. Its eight records exist for numerical correctness rehearsals
only; they are not the historical 1,024-record performance campaign.
