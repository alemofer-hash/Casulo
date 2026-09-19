from __future__ import annotations

import argparse
import ipaddress
import json
import signal
import threading
from pathlib import Path

from casulo.family.audit import AuditLog
from casulo.family.config import FamilyConfig
from casulo.family.gateway import FamilyGateway
from casulo.family.memory import FamilySessionMemory
from casulo.family.runtime import FamilyRuntime
from casulo.family.scheduler import FamilyJobStore
from casulo.family.security import DeviceRegistry
from casulo.family.supervisor import FamilySupervisor

from .family_model_adapter import FamilyLocalModelAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Casulo Family Day 4 HTTPS Gateway")
    parser.add_argument("--bind-host", required=True)
    parser.add_argument("--bind-port", type=int, default=8443)
    parser.add_argument("--approved-network", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tls-cert", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--owner-token-file", type=Path, required=True)
    parser.add_argument("--pwa-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True)
    owner_token = args.owner_token_file.read_text(encoding="ascii").strip()
    if len(owner_token) < 32:
        raise RuntimeError("owner token inválido")
    bind = ipaddress.ip_address(args.bind_host)
    config = FamilyConfig(
        bind_host=args.bind_host,
        bind_port=args.bind_port,
        queue_capacity=2,
        mock_only=False,
        lan_enabled=not bind.is_loopback,
        require_device_auth=True,
        approved_network=args.approved_network,
        tls_certfile=args.tls_cert.resolve(),
        tls_keyfile=args.tls_key.resolve(),
    )
    adapter = FamilyLocalModelAdapter(
        cache_root=args.cache_root,
        manifest=args.manifest,
        max_generated_tokens=256,
        minimum_available_ram_bytes=config.minimum_available_ram_bytes,
        minimum_start_available_ram_bytes=5 * 1_024**3,
        minimum_disk_free_bytes=config.minimum_disk_free_bytes,
    )
    registry = DeviceRegistry(state / "devices.sqlite3")
    runtime = FamilyRuntime(
        store=FamilyJobStore(state / "jobs.sqlite3"),
        audit=AuditLog(state / "audit.jsonl"),
        memory=FamilySessionMemory(state / "memory.sqlite3"),
        supervisor=FamilySupervisor(
            adapter,
            minimum_available_ram_bytes=config.minimum_available_ram_bytes,
            minimum_disk_free_bytes=config.minimum_disk_free_bytes,
        ),
        authorized_contexts=(),
        authorization_callback=registry.is_context_active,
        config=config,
    )
    gateway = FamilyGateway(
        config=config,
        runtime=runtime,
        security=registry,
        owner_token=owner_token,
        pwa_root=args.pwa_root,
    )
    stop = threading.Event()

    def request_stop(_signum=None, _frame=None) -> None:
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)
    try:
        gateway.start()
        print(
            json.dumps(
                {
                    "status": "READY",
                    "gateway": gateway.base_url,
                    "runtime": adapter.runtime_address,
                    "runtime_loopback_only": True,
                    "queue_capacity": config.queue_capacity,
                    "owner_token_printed": False,
                    "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
                    "temperature_telemetry_collected_by_runner": False,
                    "temperature_claim": "NONE",
                }
            ),
            flush=True,
        )
        stop.wait()
    finally:
        gateway.close()
        runtime.close()
        registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
