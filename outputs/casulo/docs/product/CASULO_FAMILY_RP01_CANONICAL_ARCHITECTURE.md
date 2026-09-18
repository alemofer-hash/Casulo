# CASULO FAMILY RP0.1 — canonical architecture

Status: selected from Day 0 evidence; implementation begins on `rp0.1-family`.

## Process topology

```text
Family PWA
  -> HTTPS :8443 (the only LAN listener)
  -> Casulo Family Gateway
       -> authenticated user + paired device
       -> quotas, request validation, correlation ID
       -> persistent scheduler (one heavy generation at a time)
       -> Family Supervisor (loopback/in-process contract)
            -> owner model adapter -> llama-server 127.0.0.1:8081
            -> ASR adapter          -> 127.0.0.1:8082
            -> TTS adapter          -> 127.0.0.1:8083
            -> per-user memory/RAG  -> SQLite/FTS5
            -> tool workers         -> deny-by-default
```

Only the gateway may bind to a selected LAN interface. Internal services must reject non-loopback bindings. There is no public internet listener, router forwarding, UPnP, paid API, or cloud inference fallback.

## Code placement

- `src/casulo/family/contracts.py`: versioned request, event, identity, device, and receipt types.
- `src/casulo/family/gateway.py`: HTTP/SSE boundary; loopback mock first, HTTPS/LAN only after the security gate.
- `src/casulo/family/supervisor.py`: model proposal validation, bounded step loop, policy, and receipts.
- `src/casulo/family/scheduler.py`: persistent queue and the single-heavy-job invariant.
- `src/casulo/family/memory.py`: user-scoped SQLite/FTS5 namespaces, ACL, provenance, and lifecycle.
- `src/casulo/family/audit.py`: append-only JSONL with correlation IDs and redaction.
- `src/casulo/family/mock_engine.py`: deterministic Day 1 adapter only; it must never be reported as model inference.
- `private/casulo-owner/src/casulo_owner/family_model_adapter.py`: integration with the existing loopback `LocalModelRuntime`.
- `apps/casulo-family-pwa`: mobile-first PWA added independently from the Tauri owner UI.
- `schemas/family`: wire schemas consumed by server and client.
- `tests/family`: contract, isolation, queue, network-binding, and end-to-end smoke tests.

## Initial protocols

- Health: `GET /v1/health` returns component states without secrets.
- Submit: `POST /v1/chat` validates user/device/session and returns a job identifier.
- Stream: `GET /v1/jobs/{job_id}/events` emits ordered SSE events with one terminal event.
- Cancel: `POST /v1/jobs/{job_id}/cancel` is idempotent and auditable.
- Pair/revoke endpoints are specified now but remain disabled until the device-security gate.

All payloads are bounded and versioned. A model response cannot grant capability, choose a user namespace, bypass the queue, or execute a tool directly.

## Persistence boundaries

- Runtime state lives outside Git under `%LOCALAPPDATA%\Casulo\family`.
- Separate logical database namespaces are keyed by immutable user IDs; queries always require an authenticated user context.
- Device credentials are stored as salted hashes or OS-protected secrets, never in Git or logs.
- Raw audio is ephemeral by default.
- Every mutation carries a correlation ID, receipt, previous-state reference, and rollback or explicit non-reversible classification.

## Resource policy

- Initial model context: 8192 tokens.
- Exactly one heavy generation may run; other requests remain queued.
- One main model resident at a time.
- Automatic bootstrap or model acquisition stops before disk free space would fall below 30 GB.
- Internal event and response sizes, timeouts, queue depth, and tool steps are bounded by configuration.

## Reuse decisions

- Reuse the existing engine contracts, capability broker, receipts, T/TCAP validation, local model runtime, voice adapters, and provenance primitives only through narrow adapters and passing tests.
- Refactor `LivingMemory` behavior into a user-scoped service; do not share its current global journal between family users.
- Do not enable the cloud-standby gateway. Its test-only backpressure and replay semantics may inform tests, not runtime deployment.
- Do not extend the current Tauri UI into the LAN client; build the PWA as a separate surface.
- Do not put the historical Native OS or CASV research on the RP0.1 critical path.

## Day 1 gate

The Day 1 gate passes only when an automated local smoke proves:

1. a mock client submits a Portuguese question;
2. the loopback gateway validates a synthetic authenticated context;
3. the persistent scheduler starts exactly one mock heavy job;
4. the supervisor emits ordered events and a deterministic mock response;
5. JSONL audit records share one correlation ID and contain no prompt text marked secret;
6. cancellation and terminal-event uniqueness are tested;
7. no listener is exposed beyond loopback.
