from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.voice_candidate import (
    VoiceCandidate,
    candidate_doctor_report,
    inspect_voice_cache,
)
from casulo.product import voice_cli


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release/voice-candidates/whisper-cpp-v1.9.2.json"


def test_candidate_manifest_is_strict_and_pinned() -> None:
    candidate = VoiceCandidate.load(MANIFEST)
    assert candidate.engine_commit == "306c88f4d1286aec1bf96e544632897886af5501"
    assert candidate.model_size_bytes == 190_085_487
    assert candidate.requires_user_consent


def test_doctor_is_read_only_when_cache_does_not_exist(tmp_path) -> None:
    cache = tmp_path / "missing-cache"
    report = candidate_doctor_report(VoiceCandidate.load(MANIFEST), cache)
    assert not cache.exists()
    assert report["download_performed"] is False
    assert report["asr_pt_br"] == "NOT_INSTALLED"
    assert not report["ready"]


def test_cache_requires_source_receipt_model_hash_and_bridge(tmp_path, monkeypatch) -> None:
    candidate = VoiceCandidate.load(MANIFEST)
    monkeypatch.setattr(
        "casulo.product.voice_candidate._git_checkout_matches",
        lambda source_dir, expected_commit: True,
    )
    cache = tmp_path / "voice"
    source = cache / "sources" / candidate.engine_name / candidate.engine_commit
    source.mkdir(parents=True)
    (source / "SOURCE.json").write_text(
        json.dumps(
            {
                "schema": "casulo-voice-source/1.0",
                "repository": candidate.engine_repository,
                "commit": candidate.engine_commit,
            }
        ),
        encoding="utf-8",
    )
    (source / "source/include").mkdir(parents=True)
    (source / "source/CMakeLists.txt").write_text("project(fake)", encoding="utf-8")
    (source / "source/include/whisper.h").write_text("/* fake */", encoding="utf-8")
    # A wrong-sized lookalike must never make the adapter ready.
    model = cache / "models" / f"{candidate.model_sha256}-{candidate.model_name}"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"not the model")
    platform = __import__("sys").platform
    library = (
        "casulo_whisper_bridge.dll"
        if platform == "win32"
        else "libcasulo_whisper_bridge.dylib"
        if platform == "darwin"
        else "libcasulo_whisper_bridge.so"
    )
    binary = cache / "bin" / library
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"bridge")
    inspection = inspect_voice_cache(candidate, cache)
    assert inspection.source_verified
    assert inspection.model_present
    assert not inspection.model_verified
    assert not inspection.bridge_loadable
    assert not inspection.ready


def test_invalid_candidate_hash_fails_closed(tmp_path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["model"]["sha256"] = "0" * 63
    invalid = tmp_path / "candidate.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PlatformError, match="SHA-256"):
        VoiceCandidate.load(invalid)


def test_candidate_names_cannot_escape_cache(tmp_path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["engine"]["name"] = "../../owner"
    invalid = tmp_path / "candidate-path.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PlatformError, match="caminhos"):
        VoiceCandidate.load(invalid)


def test_voice_doctor_exit_code_marks_missing_without_mutation(tmp_path, capsys) -> None:
    cache = tmp_path / "never-created"
    assert voice_cli.main(["doctor", "--manifest", str(MANIFEST), "--cache", str(cache)]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["download_performed"] is False
    assert report["required_consent_phrase"].endswith("190085487_BYTES")
    assert not cache.exists()
