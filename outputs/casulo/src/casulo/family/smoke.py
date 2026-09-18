from __future__ import annotations

import json
import tempfile
import urllib.request
from pathlib import Path

from .audit import AuditLog
from .config import FamilyConfig
from .contracts import AuthContext
from .gateway import FamilyGateway
from .memory import MockFamilyMemory
from .runtime import FamilyRuntime
from .scheduler import FamilyJobStore
from .supervisor import DeterministicMockEngine, FamilySupervisor


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="casulo-family-day1-") as temporary:
        root = Path(temporary)
        auth = AuthContext("owner", "device-smoke")
        store = FamilyJobStore(root / "family.sqlite3")
        runtime = FamilyRuntime(
            store=store,
            audit=AuditLog(root / "audit.jsonl"),
            memory=MockFamilyMemory(root / "memory.sqlite3"),
            supervisor=FamilySupervisor(DeterministicMockEngine()),
            authorized_contexts=(auth,),
        )
        gateway = FamilyGateway(config=FamilyConfig(), runtime=runtime)
        gateway.start()
        try:
            body = json.dumps({"message": "Olá, Casulo"}).encode("utf-8")
            request = urllib.request.Request(
                gateway.base_url + "/v1/chat",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Casulo-User": auth.user_id,
                    "X-Casulo-Device": auth.device_id,
                },
            )
            response = json.loads(urllib.request.urlopen(request, timeout=5).read())
            stream = urllib.request.Request(
                gateway.base_url + f"/v1/jobs/{response['job_id']}/events",
                headers={
                    "X-Casulo-User": auth.user_id,
                    "X-Casulo-Device": auth.device_id,
                },
            )
            payload = urllib.request.urlopen(stream, timeout=10).read().decode("utf-8")
            if "event: COMPLETED" not in payload or "[MOCK LOCAL]" not in payload:
                raise RuntimeError("smoke incompleto")
            memories = runtime.memory.recent(auth.user_id)
            if len(memories) != 1 or memories[0].correlation_id != response["correlation_id"]:
                raise RuntimeError("memória mock incompleta")
            print(
                json.dumps(
                    {
                        "status": "FAMILY_DAY1_MOCK_PASS",
                        "job_id": response["job_id"],
                        "correlation_id": response["correlation_id"],
                        "listener": gateway.address[0],
                        "mock_only": True,
                    },
                    sort_keys=True,
                )
            )
            return 0
        finally:
            gateway.close()
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
