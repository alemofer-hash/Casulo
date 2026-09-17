# Casulo SO Research Preview 0.1 demo runbook

## Automated rehearsal

```powershell
python release/ci_headless.py --repeat 10
```

The command rebuilds the TCAP through the general pipeline, builds the current image, refreshes `RELEASE_MANIFEST.json` with
`release/package_release.py --verify-only`, and runs `release/demo_harness.py`. It writes
`evidence/casulo-os-rp01/g7/demo-rehearsal-10.json` and the equivalent Markdown
summary. It exits nonzero unless all ten real-QEMU rehearsals pass. A serial
fixture is permitted only to test the parser; the evidence identifies it as
synthetic and it can never satisfy G7.

## Ten-step live sequence and serial contract

| # | Demonstration | Required machine-readable serial evidence |
|---:|---|---|
| 1 | Boot identity and topology | `G1_BOOT_SMOKE=PASS`, `ARCH=x86_64`, `TOPOLOGY_LOGICAL_CPUS>=2` |
| 2 | Verify the exact release TCAP | `TCAP_ARTIFACT=FloodSurrogate.tcap`, `TCAP_VALIDATION=PASS`, `TCAP_HASH_SHA256=<host artifact SHA-256>` |
| 3 | Execute FloodSurrogate in isolation | `FLOOD_SURROGATE_EXECUTION=PASS`, `FLOOD_SURROGATE_EXIT_STATUS=0`, `PROCESS_SEPARATE_CR3=PASS`, `RING3_PROCESSES>=1` |
| 4 | Conventional deterministic policy | `CONVENTIONAL_POLICY=PASS` |
| 5 | Semantic deterministic policy | `SEMANTIC_POLICY=PASS` |
| 6 | Judge output equivalence | `EQUIVALENCE_JUDGE=PASS` |
| 7 | FLOW/ATTRACTOR timeline | `SCHEDULER_TIMELINE=PASS`, positive `FLOW_DISPATCHES` and `ATTRACTOR_AUDIT_DISPATCHES` |
| 8 | Audit non-starvation | `NON_STARVATION=PASS`, `AUDIT_STARVATION=0` |
| 9 | Corrupted artifact quarantine | `TCAP_CORRUPT_RESULT=QUARANTINE`, `TCAP_CORRUPT_EXECUTED=0` |
| 10 | Honest measurements and supported exit | `TIMING_STATUS=measured|unavailable`, `ENERGY_STATUS=measured|unavailable`, `G7_DEMO_COMPLETE=PASS`, `SHUTDOWN_PATH=isa-debug-exit/0.1`, `REBOOT_PATH=8042-reset-probe-validated/0.1`, QEMU exit code 33 |

The harness also verifies `RELEASE_MANIFEST.json`, the image and TCAP hashes,
parses the unmodified TCAP on the host, flips one byte in memory, and requires
the host parser to reject that controlled corruption. Host rejection is a
preflight check, not a substitute for the kernel-side step 9 evidence.

Markers must appear once and in the table order. Measurements must appear only
after `EQUIVALENCE_JUDGE=PASS`. Missing, duplicated, conflicting or out-of-order
markers block the rehearsal. The runner never inserts markers into QEMU output.

Any step not backed by current evidence is reported as `BLOCKED` (pending
implementation) during rehearsal; the script never simulates a PASS marker for
missing kernel behavior.

## Shell and platform probes

The boot trace also requires the bounded read-only Casulo shell self-test. The
preview shell parses and dispatches immutable inspection commands; it does not
claim an interactive line editor or mutation commands.

Panic and reboot are intentionally exercised with separate probe images:

```powershell
python os/tools/run_kernel_probes.py
```

The panic probe must emit a structured `CASULO_PANIC_DUMP` and exit 35. The
reboot probe issues the 8042 reset command under QEMU `-no-reboot`, must exit
zero and must not return. The normal demo retains debug-exit code 33 so the
ordered ten-step trace can be validated deterministically.
