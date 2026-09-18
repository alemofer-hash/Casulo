# CASULO FAMILY RP0.1 — Day 1 integrated mock slice

Date: 2026-09-17
Branch: `rp0.1-family`
Gate result: `FAMILY_RP01_DAY1_MOCK_PASS`

## Delivered boundary

The new `casulo.family` package is a bounded, standard-library-only integration
slice. A synthetic client can submit a Portuguese question to a loopback HTTP
gateway, receive ordered SSE events, and trace one correlation ID through the
persistent scheduler, supervisor, mock memory, and append-only audit log.

- The gateway refuses non-loopback configuration and accepts bounded JSON only.
- Synthetic user/device contexts are allow-listed by the runtime.
- SQLite persists jobs and events, serializes heavy work, and enforces one
  terminal event per job.
- The deterministic engine labels every response `[MOCK LOCAL]`; this is not a
  model-inference claim.
- The Day 1 memory boundary persists only synthetic completion summaries and
  requires a user namespace on every read.
- The JSONL audit is hash-chained, carries the correlation ID, and rejects
  prompt-, credential-, secret-, password-, token-, and free-text-like fields.
- Versioned JSON Schemas freeze the chat request and ordered event wire shapes.

## Protocol exercised

1. `GET /v1/health` reports `DAY1_MOCK_ONLY` without authentication material.
2. `POST /v1/chat` accepts a bounded message plus synthetic user/device headers.
3. `GET /v1/jobs/{job_id}/events` returns ordered SSE with exactly one terminal
   event.
4. `POST /v1/jobs/{job_id}/cancel` is idempotent at the runtime/store boundary.

The smoke listener reported `127.0.0.1`. `FamilyConfig` rejects `0.0.0.0` and
all other non-loopback addresses. HTTPS and a selected LAN listener remain
disabled until the device-pairing/security gate.

## Verification

```text
python -m pytest -q tests/family ...
4 passed in 2.15s

python -m casulo.family.smoke
FAMILY_DAY1_MOCK_PASS; listener=127.0.0.1; mock_only=true

python -m pytest -q tests/product tests/family tests/test_casulo.py ...
773 passed, 1 skipped, 42 subtests passed in 125.85s

python -m compileall -q src/casulo/family tests/family
COMPILEALL_PASS
```

The complete command list, JUnit hash, source hashes, and gate assertions are in
`evidence/family-rp01/day1-mock-slice.json`.

## Explicit non-claims

- No LLM, llama.cpp, model weights, ASR, or TTS were started or benchmarked.
- No PWA, HTTPS certificate, device credential, pairing, revocation, or LAN
  exposure exists in this slice.
- The synthetic headers are test context, not production authentication.
- Mock memory is not the Day 5 SQLite/FTS5 RAG implementation.
- The gateway currently returns a completed event snapshot as SSE; durable live
  reconnect/replay semantics belong to the Gateway gate.
- No paid API, cloud inference, firewall change, port forwarding, or external
  listener was used.

## Next gate

Day 2: select and freeze the local model runtime, acquire an official compatible
`llama.cpp` build and a licensed 7–9B quantized model without breaching the
30 GB free-space floor, bind `llama-server` to loopback only, benchmark CPU and
available acceleration profiles, and preserve the chosen profile with hashes.
