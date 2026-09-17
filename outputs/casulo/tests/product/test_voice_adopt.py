from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.voice_adopt import (
    _clone_exact_source,
    _remove_staging,
    adopt_voice_candidate,
)
from casulo.product.voice_candidate import VoiceCacheInspection, VoiceCandidate


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release/voice-candidates/whisper-cpp-v1.9.2.json"


def test_adoption_requires_exact_consent_before_mutating_cache(tmp_path) -> None:
    candidate = VoiceCandidate.load(MANIFEST)
    cache = tmp_path / "voice"
    with pytest.raises(PlatformError, match="consentimento ausente"):
        adopt_voice_candidate(candidate, cache, consent="sim")
    assert not cache.exists()


def test_adoption_is_transactional_and_seals_receipt(tmp_path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    model_bytes = b"test-model-content"
    payload["model"]["size_bytes"] = len(model_bytes)
    payload["model"]["sha256"] = hashlib.sha256(model_bytes).hexdigest()
    manifest = tmp_path / "candidate.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    candidate = VoiceCandidate.load(manifest)

    def source_fetcher(selected, target):
        (target / "include").mkdir(parents=True)
        (target / "CMakeLists.txt").write_text("project(test)", encoding="utf-8")
        (target / "include/whisper.h").write_text("/* test */", encoding="utf-8")
        return selected.engine_commit

    def model_fetcher(selected, target):
        target.write_bytes(model_bytes)

    cache = tmp_path / "voice"
    report = adopt_voice_candidate(
        candidate,
        cache,
        consent=candidate.consent_phrase,
        source_fetcher=source_fetcher,
        model_fetcher=model_fetcher,
    )
    assert report["consent_recorded"] is True
    assert report["build_performed"] is False
    assert report["enabled"] is False
    assert Path(report["model_path"]).read_bytes() == model_bytes
    receipt = json.loads((cache / "ADOPTION.json").read_text(encoding="utf-8"))
    assert receipt["model_sha256"] == candidate.model_sha256


def test_bad_model_is_rejected_and_staging_removed(tmp_path) -> None:
    candidate = VoiceCandidate.load(MANIFEST)

    def source_fetcher(selected, target):
        (target / "include").mkdir(parents=True)
        (target / "CMakeLists.txt").write_text("project(test)", encoding="utf-8")
        (target / "include/whisper.h").write_text("/* test */", encoding="utf-8")
        return selected.engine_commit

    def bad_model_fetcher(selected, target):
        target.write_bytes(b"wrong")

    cache = tmp_path / "voice"
    with pytest.raises(PlatformError, match="tamanho/SHA-256"):
        adopt_voice_candidate(
            candidate,
            cache,
            consent=candidate.consent_phrase,
            source_fetcher=source_fetcher,
            model_fetcher=bad_model_fetcher,
        )
    assert not list(cache.rglob(".staging-*"))
    assert not (cache / "ADOPTION.json").exists()
    assert not list(cache.rglob("SOURCE.json"))
    assert not list(cache.rglob("source"))


def test_adoption_reuses_fully_verified_cache_without_fetching(tmp_path, monkeypatch) -> None:
    candidate = VoiceCandidate.load(MANIFEST)
    cache = tmp_path / "voice"
    cache.mkdir()
    adoption = {
        "schema": "casulo-voice-adoption/1.0",
        "consent_recorded": True,
        "engine_commit": candidate.engine_commit,
        "model_sha256": candidate.model_sha256,
    }
    (cache / "ADOPTION.json").write_text(json.dumps(adoption), encoding="utf-8")
    inspection = VoiceCacheInspection(
        cache_root=cache,
        source_dir=cache / "source",
        source_receipt=cache / "SOURCE.json",
        model_path=cache / "model.bin",
        bridge_path=cache / "bridge.dll",
        source_verified=True,
        model_present=True,
        model_verified=True,
        bridge_present=False,
        free_bytes=1_000_000_000,
        ready=False,
    )
    monkeypatch.setattr(
        "casulo.product.voice_adopt.inspect_voice_cache",
        lambda *args: inspection,
    )

    def forbidden(*args):
        raise AssertionError("cache verificado não pode acessar rede")

    report = adopt_voice_candidate(
        candidate,
        cache,
        consent=candidate.consent_phrase,
        source_fetcher=forbidden,
        model_fetcher=forbidden,
    )
    assert report["reused_verified_cache"] is True
    assert report["model_downloaded_this_run"] is False


def test_git_clone_enables_windows_long_paths(tmp_path, monkeypatch) -> None:
    candidate = VoiceCandidate.load(MANIFEST)
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, stdout=candidate.engine_commit + "\n")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr("casulo.product.voice_adopt.shutil.which", lambda _name: "git")
    monkeypatch.setattr("casulo.product.voice_adopt.subprocess.run", fake_run)

    assert _clone_exact_source(candidate, tmp_path / "source") == candidate.engine_commit
    assert calls[0][1:5] == [
        "-c",
        "core.longpaths=true",
        "-c",
        "core.autocrlf=false",
    ]


def test_staging_cleanup_clears_readonly_checkout_files(tmp_path) -> None:
    parent = tmp_path / "voice"
    staging = parent / ".staging-source-test"
    checkout_file = staging / ".git" / "objects" / "pack" / "pack.idx"
    checkout_file.parent.mkdir(parents=True)
    checkout_file.write_bytes(b"index")
    checkout_file.chmod(0o444)

    _remove_staging(staging, parent)

    assert not staging.exists()


def test_second_model_reuses_verified_source_and_gets_own_receipt(tmp_path, monkeypatch) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    model_bytes = b"second-model"
    payload["model"]["name"] = "second.bin"
    payload["model"]["size_bytes"] = len(model_bytes)
    payload["model"]["sha256"] = hashlib.sha256(model_bytes).hexdigest()
    manifest = tmp_path / "second.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    candidate = VoiceCandidate.load(manifest)
    cache = tmp_path / "voice"
    source_root = cache / "sources" / candidate.engine_name / candidate.engine_commit
    source = source_root / "source"
    source.mkdir(parents=True)
    receipt = source_root / "SOURCE.json"
    receipt.write_text("preserve-source-receipt", encoding="utf-8")
    model = cache / "models" / f"{candidate.model_sha256}-{candidate.model_name}"
    bridge = cache / "bin/casulo_whisper_bridge.dll"
    inspection = VoiceCacheInspection(
        cache_root=cache,
        source_dir=source,
        source_receipt=receipt,
        model_path=model,
        bridge_path=bridge,
        source_verified=True,
        model_present=False,
        model_verified=False,
        bridge_present=True,
        free_bytes=1_000_000_000,
        bridge_loadable=True,
        ready=False,
    )
    monkeypatch.setattr("casulo.product.voice_adopt.inspect_voice_cache", lambda *args: inspection)

    def forbidden_source(*_args):
        raise AssertionError("source verificado não pode ser baixado novamente")

    def model_fetcher(_selected, target):
        target.write_bytes(model_bytes)

    report = adopt_voice_candidate(
        candidate,
        cache,
        consent=candidate.consent_phrase,
        source_fetcher=forbidden_source,
        model_fetcher=model_fetcher,
    )
    assert report["model_sha256"] == candidate.model_sha256
    assert receipt.read_text(encoding="utf-8") == "preserve-source-receipt"
    assert (cache / "adoptions" / f"{candidate.model_sha256}.json").is_file()
    assert model.read_bytes() == model_bytes


def test_exact_consent_can_seal_a_preexisting_fully_verified_model(tmp_path, monkeypatch) -> None:
    candidate = VoiceCandidate.load(MANIFEST)
    cache = tmp_path / "voice"
    inspection = VoiceCacheInspection(
        cache_root=cache,
        source_dir=cache / "source",
        source_receipt=cache / "SOURCE.json",
        model_path=cache / "model.bin",
        bridge_path=cache / "bridge.dll",
        source_verified=True,
        model_present=True,
        model_verified=True,
        bridge_present=True,
        free_bytes=1_000_000_000,
        bridge_loadable=True,
        ready=True,
    )
    monkeypatch.setattr("casulo.product.voice_adopt.inspect_voice_cache", lambda *args: inspection)

    def forbidden(*_args):
        raise AssertionError("reconciliação não pode acessar rede")

    report = adopt_voice_candidate(
        candidate,
        cache,
        consent=candidate.consent_phrase,
        source_fetcher=forbidden,
        model_fetcher=forbidden,
    )
    assert report["reconciled_verified_cache"] is True
    assert report["reused_verified_cache"] is True
    receipt = cache / "adoptions" / f"{candidate.model_sha256}.json"
    assert receipt.is_file()
