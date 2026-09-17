from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_tts_candidate_is_pinned_but_license_blocked_and_disabled() -> None:
    candidate = json.loads(
        (
            ROOT
            / "release/voice-candidates/tts-sherpa-edresson-license-review.json"
        ).read_text(encoding="utf-8")
    )
    assert candidate["status"] == "LICENSE_REVIEW_REQUIRED_NOT_ADOPTED"
    assert candidate["engine"]["commit"] == "3dc7c569f31ca2cd4a20ed6f7db780327e6714c5"
    assert candidate["engine"]["top_level_license"] == "Apache-2.0"
    assert "GPL-3.0" in candidate["engine"]["blocking_license"]
    assert candidate["voice"]["model"]["sha256"] == (
        "de4cecee38b30bb1a6378a337af605d59f0c377df702c6a6752870db8991cd84"
    )
    assert candidate["voice"]["model_card"]["dataset_license"] == "CC-BY-4.0"
    assert candidate["downloaded"] is False
    assert candidate["enabled_by_default"] is False
