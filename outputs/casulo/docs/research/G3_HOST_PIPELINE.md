# G3 host pipeline evidence

The G3 host slice produces a real freestanding x86-64 workload rather than a
renamed C source file. `src/casulo/t/learn_native.py` accepts only the general
versioned IR and Metamorfose graph, validates their operation sequence,
permissions and deterministic contract, derives a bounded resource contract,
and emits the native payload and `.tcap`.

The historical `learn -> C99` route remains available as a named baseline.
New historical-format artifacts first form their code-generating plan from the
general IR/graph. The old parser runs only as an equivalence oracle and a
disagreement rejects the build. It cannot populate the native plan.

What this slice proves:

- deterministic T -> IR -> graph -> plan -> native -> TCAP construction;
- a raw position-independent x86-64 payload with a fixed entry offset and no
  remaining relocations;
- canonical TCAP round-trip, hashes, provenance and bounded resources;
- fail-closed graph/instruction disagreement and byte-corruption rejection;
- explicit unmeasured energy and unexecuted kernel quality state.

What it does not prove:

- that the current Casulo kernel loads or executes the payload;
- process isolation or syscall enforcement;
- numerical equivalence on the Casulo kernel;
- performance, energy or superiority over any baseline.

Those are integration gates, not properties a host compiler unit test can
honestly substitute.
