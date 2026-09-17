# Casulo SO G7 automated demo evidence

- Status: **PASS**
- Evidence kind: `real_qemu_rehearsal`
- Rehearsals: 10/10
- Serial validations passed: 10/10
- TCAP host validation: PASS
- Release manifest validation: PASS
- Physical device written: no

## Ten-step contract (first rehearsal)

| # | Step | Status | Evidence gap |
|---:|---|---|---|
| 1 | boot identity and topology | PASS | none |
| 2 | TCAP integrity and provenance | PASS | none |
| 3 | isolated FloodSurrogate execution | PASS | none |
| 4 | conventional deterministic policy | PASS | none |
| 5 | semantic deterministic policy | PASS | none |
| 6 | equivalence judge | PASS | none |
| 7 | FLOW and ATTRACTOR timeline | PASS | none |
| 8 | audit non-starvation | PASS | none |
| 9 | corrupted TCAP quarantine without execution | PASS | none |
| 10 | honest measurements and supported exit | PASS | none |

Synthetic serial fixtures validate only the parser and can never satisfy G7.
A blocked result is expected until the kernel emits the complete G3/G4 demo protocol.
