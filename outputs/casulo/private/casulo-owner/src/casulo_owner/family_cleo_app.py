"""Day 6 owner-only, loopback HTTPS launcher. No mobile enrollment."""
from __future__ import annotations

import hashlib
import csv
import json
import os
import signal
import subprocess
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path

from casulo.family.audit import AuditLog
from casulo.family.cleo_gateway import CleoGateway
from casulo.family.config import FamilyConfig
from casulo.family.ephemeral import EphemeralFamilyJobStore
from casulo.family.memory import FamilyRagMemory
from casulo.family.persona import PersonaResolver
from casulo.family.runtime import FamilyRuntime
from casulo.family.security import DeviceRegistry
from casulo.family.supervisor import FamilySupervisor
from casulo.family.voice import VoiceCoordinator
from casulo.family.voice_service import LocalVoiceService

from .family_gateway_app import build_parser
from .family_model_adapter import FamilyLocalModelAdapter


def sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def voice_paths(voice_root, lock_file):
    lock = json.loads(Path(lock_file).read_text(encoding="utf-8"))["asr"]
    library = voice_root / "bin/casulo_whisper_bridge.dll"
    model = voice_root / "models" / (lock["model_sha256"] + "-" + lock["model"])
    if sha256(library) != lock["library_sha256"] or sha256(model) != lock["model_sha256"]:
        raise RuntimeError("VOICE_DEPENDENCY_HASH_MISMATCH")
    return library, model


def restrict_state_directory(state):
    if os.name != "nt":
        state.chmod(0o700)
        return "chmod-0700"
    identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                              capture_output=True, text=True, check=True).stdout.strip()
    sid = next(csv.reader([identity]))[1]
    subprocess.run(["icacls", str(state), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)(F)"],
                   capture_output=True, check=True)
    return "owner-only-inherited"


@contextmanager
def cleo_stack(args, *, harness=False, unlocked=None):
    if args.bind_host != "127.0.0.1":
        raise ValueError("Day 6 host launch is loopback only; LAN enrollment is Day 7")
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True)
    restrict_state_directory(state)
    slot_path = state / "empty-slot-actions"
    slot_path.mkdir(exist_ok=True)
    config = FamilyConfig(bind_host="127.0.0.1", bind_port=args.bind_port,
                          mock_only=False, require_device_auth=True,
                          tls_certfile=args.tls_cert, tls_keyfile=args.tls_key,
                          max_request_bytes=900000, queue_capacity=2)
    library, model = voice_paths(args.voice_root, args.dependency_lock)
    with ExitStack() as cleanup:
        registry = DeviceRegistry(state / "devices.sqlite3")
        cleanup.callback(registry.close)
        kwargs = {} if unlocked is None else {"unlocked": unlocked}
        resolver = PersonaResolver(args.persona_root, active=registry.is_context_active,
                                   harness=harness, **kwargs)
        adapter = FamilyLocalModelAdapter(cache_root=args.cache_root, manifest=args.manifest,
                                          max_generated_tokens=64,
                                          minimum_start_available_ram_bytes=5*1024**3,
                                          slot_action_path=slot_path)
        memory = FamilyRagMemory(state / "memory.sqlite3", embedding_card=args.embedding_card,
                                 embedding_sha256=args.embedding_sha256)
        cleanup.callback(memory.close)
        store = EphemeralFamilyJobStore()
        cleanup.callback(store.close)
        runtime = FamilyRuntime(store=store, audit=AuditLog(state / "audit.jsonl"),
                                memory=memory, supervisor=FamilySupervisor(adapter),
                                authorized_contexts=(), authorization_callback=registry.is_context_active,
                                persona_resolver=resolver, config=config)
        # runtime owns memory/store; close methods are idempotent in this stack.
        cleanup.pop_all()
        cleanup.callback(registry.close)
        cleanup.callback(runtime.close)
        if not runtime.supervisor.ready:
            raise RuntimeError("MODEL_NOT_READY")
        service = LocalVoiceService(library, model)
        cleanup.callback(service.close)
        service.start()
        voice = VoiceCoordinator(runtime, service)
        cleanup.callback(voice.close)
        token = args.owner_token_file.read_text(encoding="ascii").strip()
        gateway = CleoGateway(config=config, runtime=runtime, security=registry,
                              owner_token=token, pwa_root=args.pwa_root, voice=voice)
        gateway.start()
        cleanup.callback(gateway.close)
        yield gateway, runtime, voice, service, registry, resolver, adapter


def main(argv=None):
    parser = build_parser()
    parser.description = "Casulo Family Day 6 Cleo (owner host, loopback HTTPS)"
    parser.add_argument("--voice-root", type=Path, required=True)
    parser.add_argument("--persona-root", type=Path, required=True)
    parser.add_argument("--dependency-lock", type=Path, required=True)
    args = parser.parse_args(argv)
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    with cleo_stack(args) as (gateway, runtime, voice, service, _, _, adapter):
        print(json.dumps({"status": "READY", "gateway": gateway.base_url,
                          "model": adapter.runtime_address, "voice_loopback": service.address,
                          "host_binding": "local_owner_token_and_private_route_required",
                          "temperature_monitoring": "EXTERNAL_MANUAL_HWINFO",
                          "temperature_telemetry_collected_by_runner": False,
                          "temperature_claim": "NONE"}), flush=True)
        stop.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
