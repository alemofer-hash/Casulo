from __future__ import annotations

from pathlib import Path

from tools.casulo_semantic_multiverse import doctor, inspect_state


ROOT = Path(__file__).resolve().parents[2]


def test_doctor_is_read_only_and_preserves_g10() -> None:
    result = doctor(ROOT)
    assert result["read_only"]
    assert not result["mutations_performed"] and not result["network_access_performed"]
    assert all(
        value for name, value in result["checks"].items()
        if name.startswith("g10:") or name in {"g10_state", "cloud_release_locked", "external_media_absent", "public_frozen"}
    )
    # A changed source artifact must make the previous sealed handoff stale,
    # never silently claim that it is still the current inspected release.
    if result["checks"]["semantic_artifacts_verified"]:
        assert result["ready"]
    else:
        assert not result["ready"]


def test_inspection_does_not_create_state(tmp_path) -> None:
    result = inspect_state(tmp_path / "absent")
    assert result == {"schema": "casulo.semantic-multiverse-inspection/1.0", "read_only": True, "session_count": 0, "sessions": []}
    assert not (tmp_path / "absent").exists()
