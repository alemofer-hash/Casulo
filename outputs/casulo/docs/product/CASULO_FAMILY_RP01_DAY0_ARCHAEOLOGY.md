# CASULO FAMILY RP0.1 — Day 0 archaeology

Date: 2026-09-17
Branch: `rp0.1-family`
Starting commit: `d9aca5461af31fcb24000f2872825c52c5b80e64`
Raw baseline: `100885dc009aed077a3ec2ac7d82a8b8de6b30a7`
Raw tree: `6ce76021d0991097951168c423137977d8cc9e78`
Raw tag: `casulo-stage0-raw-2026-09-17`

## Scope and method

This report distinguishes running implementation, tests, specifications, generated evidence, and historical artifacts. It does not treat documentation as proof of implementation. No existing source was reorganized or corrected before the baseline below.

The root repository is the preservation and orchestration boundary. The current application source candidate is `outputs/casulo`, which contains the Python package, owner adapter, Rust crates, UI, schemas, and product tests. Historical outputs remain in place and are not silently promoted into the new family runtime.

## Repository map

- Root repository at `C:\Users\guimo\Downloads\ex`: 31,550 tracked files at the policy commit.
- `outputs/casulo`: 31,285 tracked files in the raw snapshot.
- Active implementation: 211 files under `outputs/casulo/src`, including 56 modules under `src/casulo/product`.
- Direct product tests: 166 files under `outputs/casulo/tests` before generated/test evidence is counted.
- Existing manifests include the main Python package, owner/private and public editions, Rust OS/runtime crates, a Tauri owner UI, a native voice CMake project, and the cloud-standby Python package.
- Most tracked volume under `outputs/casulo` is evidence or generated history: 19,596 product-demo files, 4,442 outputs, 2,606 test-temp files, 1,668 release files, and 639 reproduction-temp files.

## Executable baseline

Command family:

```text
python -m pytest -q tests/product tests/test_casulo.py tests/test_t_frontend.py tests/test_t_semantics_ir.py tests/test_t_workspace.py tests/test_t_tcap.py tests/test_t_metamorphosis.py::TMetamorfoseGraphTests
```

Authoritative run with a writable external `basetemp`:

- 750 passed;
- 8 failed;
- 12 skipped;
- 42 subtests passed;
- 192.95 seconds reported by pytest;
- JUnit SHA-256: `85508f3fa9ff4e1128335042ecce7945db618873cfddb8329b7dd5a7cf101063`.

Five failures invoked Windows Script Host and were denied only by the execution sandbox. The same five node IDs were rerun outside that sandbox and passed 5/5 in 3.76 seconds; JUnit SHA-256: `100d285433070446ca18962badba5a986051a80312710d86cf0c3618e4718034`.

Effective baseline after the controlled environmental recheck:

- 755 passed;
- 3 failed;
- 12 skipped;
- 42 subtests passed.

The three remaining failures are textual contract tests:

1. `tests/product/test_native_block0_runner.py::test_np6_builder_and_verifier_keep_output_token_forbidden`
2. `tests/product/test_native_decoder_runner.py::test_np7_builder_enables_decoder_without_reexecuting_np6_probe`
3. `tests/product/test_native_model_probe_runner.py::test_neural_port_builder_scopes_token_claim_to_token_capable_stages`

They still assert the old stage sets ending at `np10`. The implementation in `os/tools/build_native_neural_port_image.py` consistently includes `np11` for decoder, sampling, creation, and first-token claims. This is a stale test oracle after the NP11 extension, not evidence that the implementation regressed. The red baseline is preserved before any test correction.

After the baseline was frozen, the six exact string expectations in those three files were extended to include `np11`. The focal rerun passed 3/3 in 0.80 seconds. The complete gate was then rerun outside the sandbox in a single process:

- 769 passed;
- 1 skipped;
- 42 subtests passed;
- zero failures and zero errors;
- 200.58 seconds reported by pytest;
- JUnit SHA-256: `a8092f3818864e131ac08d0c4a09f608dd32d80f96f595c5d3b87b153b770e87`.

An earlier run placed `basetemp` under the sandboxed Downloads tree and is not authoritative: it produced 274 permission errors, 8 failures, 478 passes, 10 skips, and 42 passing subtests. It is retained as environmental evidence only.

## Implementation versus specification

| Capability | Current implementation evidence | Status for Family RP0.1 |
|---|---|---|
| Local model runtime | `private/casulo-owner/src/casulo_owner/local_model_runtime.py` starts `llama-server` on `127.0.0.1`, checks `/health`, streams SSE, bounds event size, and supports cancellation. | Reusable behind an owner adapter; not yet connected to a family gateway. |
| Voice | `voice_duplex.py`, `voice_bridge.py`, `voice_candidate.py`, `whisper_worker.py`, and related tests implement local ASR/TTS contracts and barge-in. | Substantial implementation exists; device-specific quality and packaging remain risks. |
| Memory | `living_memory.py` has encrypted append-only events, hash chaining, provenance, recall, export, and explicit deletion. | Not sufficient: storage is not partitioned by authenticated family user and is not the planned SQLite/FTS5 service. |
| Queue | `hosted_shell.py` has an in-memory priority queue and cancellation hooks; cloud standby has a test-only job harness. | Not sufficient: no persistent single-heavy-job scheduler with restart recovery. |
| Tool policy | capability broker, T/TCAP, receipts, materializers, and rollback-oriented tests exist. | Reusable contracts exist; there is no family-facing agent supervisor API yet. |
| Gateway | `services/casulo-cloud-standby` implements only a `RELEASE_LOCKED` test harness; generated APIs bind loopback. | Missing: no authenticated HTTPS LAN gateway. Cloud standby must remain locked. |
| Device enrollment | No verified per-device pairing and revocation service was found in the active source. | Missing. |
| PWA | `apps/casulo-owner-ui` is a Tauri output projection that explicitly forbids network primitives and labels its data synthetic. | Not a PWA and not a family client. A separate PWA is required. |
| RAG | Local-intelligence and memory primitives exist, but no verified per-user SQLite/FTS5 ingestion path with ACL and citations is integrated. | Partial primitives only. |

## Canonical selection

1. Keep the consolidated root repository unchanged as the authoritative history and remote boundary.
2. Treat `outputs/casulo` as the source root for RP0.1 rather than copying historical code into a second project.
3. Add the family integration as a bounded package under `src/casulo/family` and tests under `tests/family`.
4. Keep `private/casulo-owner` as the owner-only adapter boundary for the local model runtime.
5. Keep `casulo-public` and `casulo-cloud-standby` isolated; Cloud remains `RELEASE_LOCKED` and is not a fallback.
6. Add a distinct browser client under `apps/casulo-family-pwa`; do not reinterpret the Tauri owner UI as a PWA.
7. Preserve all historical experiments, native work, compression research, and generated evidence as inputs, not as the default family runtime.

## Day 1 entry condition

The first integrated slice must be mock-only and loopback-only. A request must traverse client -> gateway -> supervisor -> mock engine -> streamed response with JSONL audit correlation. No LAN bind, TLS certificate, model download, voice capture, or family data is required for that mock gate.
