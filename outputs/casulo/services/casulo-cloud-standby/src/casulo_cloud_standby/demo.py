from __future__ import annotations

import json

from casulo.product.engine_contracts import CancellationToken, EngineRequest

from .gateway import CloudReleaseLock, CloudTestHarness, ReleaseLockedError


def main() -> int:
    harness = CloudTestHarness()
    request = EngineRequest(
        "request:cloud-standby-demo",
        "creation:cloud-standby-demo",
        0,
        "a" * 64,
        ("memory:explicitly-authorized-demo",),
    )
    events = tuple(harness.submit(request, CancellationToken()))
    replay = tuple(harness.submit(request, CancellationToken()))
    production_bind_denied = False
    try:
        CloudReleaseLock().production_bind("127.0.0.1", 443)
    except ReleaseLockedError:
        production_bind_denied = True

    payload = {
        "schema": "casulo-cloud-standby-demo/1.0",
        "release_state": CloudReleaseLock().state,
        "production_bind_denied": production_bind_denied,
        "events": [
            {
                "request_id": event.request_id,
                "sequence": event.sequence,
                "kind": event.kind.value,
                "message": event.message,
                "payload_sha256": event.payload_sha256,
                "protocol": event.protocol,
            }
            for event in events
        ],
        "idempotent_replay_exact": replay == events,
        "observability": harness.observability_snapshot(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if production_bind_denied and replay == events else 1


if __name__ == "__main__":
    raise SystemExit(main())
