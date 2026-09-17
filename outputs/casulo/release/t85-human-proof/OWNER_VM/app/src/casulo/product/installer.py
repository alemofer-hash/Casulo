from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import canonical_json, canonical_sha256
from .hosted_shell import ProductFeature
from .living_memory import DpapiSecretBox, LivingMemory, SecretBox
from .machine_profile import MachineProfile, calibrate_local_response, collect_machine_profile
from .platform_contracts import LocalStorage, SystemClock


class InstallationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InstallationPlan:
    feature: ProductFeature
    machine_profile_sha256: str
    status: str
    reasons: tuple[str, ...]
    download_bytes: int
    consent_phrase: str
    schema: str = "casulo-install-plan/1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "feature": self.feature.value,
            "machine_profile_sha256": self.machine_profile_sha256,
            "status": self.status,
            "reasons": list(self.reasons),
            "download_bytes": self.download_bytes,
            "estimated_download_seconds": None,
            "consent_phrase": self.consent_phrase,
            "network_access_performed": False,
            "mutations_performed": False,
            "account_required": False,
        }

    @property
    def plan_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


def plan_installation(profile: MachineProfile, feature: ProductFeature) -> InstallationPlan:
    assessment = profile.assessment(feature)
    profile_hash = str(profile.to_dict()["profile_sha256"])
    seed = canonical_sha256({"host_id": profile.host_id, "feature": feature.value})[:12].upper()
    return InstallationPlan(
        feature=feature,
        machine_profile_sha256=profile_hash,
        status="READY_TO_INITIALIZE" if assessment.status == "READY" else "NEEDS_ACTION",
        reasons=assessment.reasons,
        download_bytes=assessment.optional_download_bytes,
        consent_phrase=f"INITIALIZE_CASULO_{feature.name}_{seed}",
    )


def initialize_local_profile(
    plan: InstallationPlan,
    destination: str | Path,
    *,
    consent: str,
    secret_box: SecretBox | None = None,
    allow_test_encryption: bool = False,
) -> dict[str, Any]:
    if consent != plan.consent_phrase:
        raise InstallationError("consentimento literal do plano ausente")
    if plan.status != "READY_TO_INITIALIZE":
        raise InstallationError("plano ainda possui acoes pendentes")
    target = Path(destination).expanduser().resolve()
    receipt_path = target / "INSTALLATION.json"
    if receipt_path.is_file():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing.get("plan_sha256") != plan.plan_sha256:
            raise InstallationError("destino pertence a outro plano")
        return existing
    if target.exists():
        raise InstallationError("destino existente sem receipt Casulo")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.casulo-stage-{os.getpid()}")
    if staging.exists():
        raise InstallationError("staging existente; limpeza manual necessaria")
    try:
        storage = LocalStorage(staging)
        box = secret_box or DpapiSecretBox()
        memory = LivingMemory(
            storage=storage,
            clock=SystemClock(),
            secret_box=box,
            allow_test_encryption=allow_test_encryption,
        )
        memory.append(
            event_id=f"installation:{plan.plan_sha256}",
            kind="SYSTEM",
            subject_id="profile:local",
            text="Perfil local Casulo inicializado com memoria protegida.",
            payload={"feature": plan.feature.value, "account_required": False},
            source_ids=(f"consent:{plan.plan_sha256}",),
        )
        receipt = {
            "schema": "casulo-installation/1.0",
            "plan_sha256": plan.plan_sha256,
            "feature": plan.feature.value,
            "machine_profile_sha256": plan.machine_profile_sha256,
            "memory_encrypted": True,
            "account_created": False,
            "network_access_performed": False,
            "downloads_performed": False,
            "guide_first_message": "Ola. Eu sou seu Guia Casulo. O que vamos construir juntos?",
        }
        storage.write_atomic("INSTALLATION.json", canonical_json(receipt))
        os.replace(staging, target)
        return receipt
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Doctor e instalador consentido do Casulo")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "plan"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, default=Path.cwd())
        command.add_argument("--voice-manifest", type=Path)
        command.add_argument("--voice-cache", type=Path)
        command.add_argument("--guide-registry", type=Path)
        if name == "plan":
            command.add_argument("--feature", choices=[item.value for item in ProductFeature], required=True)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--duration-ms", type=int, default=100)
    initialize = commands.add_parser("initialize")
    initialize.add_argument("--workspace", type=Path, default=Path.cwd())
    initialize.add_argument("--feature", choices=[item.value for item in ProductFeature], required=True)
    initialize.add_argument("--destination", type=Path, required=True)
    initialize.add_argument("--consent", required=True)
    initialize.add_argument("--voice-manifest", type=Path)
    initialize.add_argument("--voice-cache", type=Path)
    initialize.add_argument("--guide-registry", type=Path)
    args = parser.parse_args(argv)
    if args.command == "calibrate":
        print(json.dumps(calibrate_local_response(duration_ms=args.duration_ms), indent=2, sort_keys=True))
        return 0
    profile = collect_machine_profile(
        args.workspace,
        voice_manifest=args.voice_manifest,
        voice_cache=args.voice_cache,
        guide_registry=args.guide_registry,
    )
    if args.command == "doctor":
        print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    plan = plan_installation(profile, ProductFeature(args.feature))
    if args.command == "plan":
        print(json.dumps({**plan.to_dict(), "plan_sha256": plan.plan_sha256}, indent=2, sort_keys=True))
        return 0
    receipt = initialize_local_profile(plan, args.destination, consent=args.consent)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
