from __future__ import annotations

from casulo_owner.alpha_demo import run


def test_owner_alpha_vertical_slice_is_complete_and_local(tmp_path) -> None:
    report = run(tmp_path / "alpha", test_encryption=True)
    assert report["cloud_used"] is False
    assert report["third_party_ai_api_used"] is False
    assert report["local_model_turn"]["third_party_ai_api_used"] is False
    assert report["local_model_registry"]["ready"] == {"guide": True, "embeddings": True}
    assert report["local_embedding_dimensions"] == 64
    assert report["permissions_preserved_during_correction"] is True
    assert report["failed_simulation_status"] == "CORRECTION_REQUIRED"
    assert report["successful_simulation_status"] == "PASS"
    assert report["real_effects_executed"] is False
    assert report["recall_status"] == "FOUND"
    assert len(report["rendered_states"]) == 12
    assert report["forge_rebuilt_after_correction"] == ["behavior", "interface"]
    assert report["forge_identity_hash_preserved"] is True
    assert report["external_api_identity_matches"] is True
    assert report["import_identity_matches"] is True
