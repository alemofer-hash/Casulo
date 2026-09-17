from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.product.hosted_shell import ProductFeature
from casulo.product.installer import InstallationError, initialize_local_profile, plan_installation
from casulo.product.living_memory import TestSecretBox
from casulo.product.machine_profile import calibrate_local_response, collect_machine_profile


def tree(root: Path) -> tuple[str, ...]:
    return tuple(sorted(path.relative_to(root).as_posix() for path in root.rglob("*")))


def test_doctor_and_plan_are_read_only(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    before = tree(tmp_path)
    profile = collect_machine_profile(workspace)
    plan = plan_installation(profile, ProductFeature.MINIMAL)
    assert tree(tmp_path) == before
    assert profile.to_dict()["mutations_performed"] is False
    assert profile.to_dict()["network_access_performed"] is False
    assert plan.to_dict()["mutations_performed"] is False
    assert plan.to_dict()["account_required"] is False


def test_profile_identity_ignores_volatile_free_space(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = collect_machine_profile(workspace).to_dict()["profile_sha256"]
    (workspace / "volatile.bin").write_bytes(b"x" * 4096)
    second = collect_machine_profile(workspace).to_dict()["profile_sha256"]
    assert second == first


def test_initialize_requires_exact_consent_and_creates_encrypted_memory(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = plan_installation(collect_machine_profile(workspace), ProductFeature.MINIMAL)
    destination = tmp_path / "profile"
    with pytest.raises(InstallationError, match="consentimento"):
        initialize_local_profile(plan, destination, consent="yes")
    assert not destination.exists()

    receipt = initialize_local_profile(
        plan,
        destination,
        consent=plan.consent_phrase,
        secret_box=TestSecretBox(),
        allow_test_encryption=True,
    )
    assert receipt["memory_encrypted"] is True
    assert receipt["account_created"] is False
    assert receipt["downloads_performed"] is False
    assert list((destination / "memory/events").glob("*.json.dpapi"))
    stored = json.loads((destination / "INSTALLATION.json").read_text(encoding="utf-8"))
    assert stored == receipt
    assert initialize_local_profile(
        plan,
        destination,
        consent=plan.consent_phrase,
        secret_box=TestSecretBox(),
        allow_test_encryption=True,
    ) == receipt


def test_existing_unowned_destination_is_never_overwritten(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = plan_installation(collect_machine_profile(workspace), ProductFeature.MINIMAL)
    destination = tmp_path / "profile"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")
    with pytest.raises(InstallationError, match="existente"):
        initialize_local_profile(plan, destination, consent=plan.consent_phrase)
    assert sentinel.read_text(encoding="utf-8") == "user data"


def test_micro_calibration_is_bounded_and_not_scientific() -> None:
    report = calibrate_local_response(duration_ms=10)
    assert report["hash_operations"] > 0
    assert report["duration_ms"] < 250
    assert report["scientific_benchmark"] is False
    assert report["mutations_performed"] is False


def test_voice_inputs_are_atomic(tmp_path) -> None:
    with pytest.raises(ValueError, match="juntos"):
        collect_machine_profile(tmp_path, voice_manifest=tmp_path / "voice.json")


def test_first_party_guide_registry_enables_guide_profile(tmp_path) -> None:
    registry = Path(__file__).resolve().parents[2] / "models/registry.json"
    profile = collect_machine_profile(tmp_path, guide_registry=registry)
    assert profile.assessment(ProductFeature.GUIDE).status == "READY"
    assert profile.to_dict()["guide"]["third_party_ai_api_required"] is False
