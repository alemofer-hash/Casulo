from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from casulo_owner.generative_model import (
    GenerativeCandidate,
    GenerativeModelError,
    adopt_candidate,
    adoption_doctor,
    adoption_plan,
)


ROOT = Path(__file__).resolve().parents[2]


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _zip_bytes(path: Path, *, traversal: bool = False, reserved: bool = False, symlink: bool = False) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if symlink:
            entry = zipfile.ZipInfo("bin/llama-server.exe")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, "target")
        else:
            name = "../escape.txt" if traversal else "bin/NUL.txt" if reserved else "bin/llama-server.exe"
            archive.writestr(name, b"runtime")
        if not traversal and not reserved and not symlink:
            archive.writestr("bin/ggml.dll", b"library")
    return path.read_bytes()


def _candidate(
    tmp_path: Path,
    *,
    traversal: bool = False,
    reserved: bool = False,
    symlink: bool = False,
) -> tuple[GenerativeCandidate, dict[str, bytes]]:
    model = b"neural-model-test-only"
    runtime = _zip_bytes(
        tmp_path / "runtime-source.zip",
        traversal=traversal,
        reserved=reserved,
        symlink=symlink,
    )
    unpacked = max(4096, len(runtime))
    payload = {
        "schema": "casulo-generative-candidate/1.0",
        "candidate_id": "test-neural-candidate",
        "model": {
            "file": "model.gguf",
            "url": "https://huggingface.co/casulo/test/resolve/revision/model.gguf",
            "bytes": len(model),
            "sha256": _sha(model),
            "license": "Apache-2.0",
        },
        "runtime": {
            "asset": "runtime.zip",
            "url": "https://github.com/casulo/test/releases/download/v1/runtime.zip",
            "bytes": len(runtime),
            "sha256": _sha(runtime),
            "license": "MIT",
            "max_unpacked_bytes": unpacked,
            "required_executable": "llama-server.exe",
        },
        "storage": {
            "minimum_reserve_bytes": 30 * 1024**3,
            "projected_adoption_peak_bytes": 2 * (len(model) + len(runtime)) + unpacked,
        },
        "network_required_after_install": False,
        "commercial_ai_api_required": False,
        "training_with_user_content": False,
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    candidate = GenerativeCandidate.load(path)
    return candidate, {candidate.model.url: model, candidate.runtime.url: runtime}


def _fetcher(blobs: dict[str, bytes]):
    def fetch(url: str, destination: Path, expected_bytes: int) -> None:
        value = blobs[url]
        assert len(value) == expected_bytes
        destination.write_bytes(value)

    return fetch


def test_repository_candidate_is_pinned_and_not_adopted() -> None:
    candidate = GenerativeCandidate.load(
        ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json"
    )
    assert candidate.model.bytes == 2_497_280_256
    assert candidate.model.sha256 == "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
    assert candidate.runtime.sha256 == "a9d95d26cf00664f2902f73cb0fd9b167a3a1f252294bb2f8b236305f57d6363"
    assert candidate.minimum_reserve_bytes == 30 * 1024**3


def test_doctor_and_plan_are_read_only_when_cache_is_missing(tmp_path: Path) -> None:
    candidate, _ = _candidate(tmp_path)
    cache = tmp_path / "missing-cache"
    before = sorted(item.name for item in tmp_path.iterdir())
    doctor = adoption_doctor(candidate, cache)
    plan = adoption_plan(candidate, cache)
    after = sorted(item.name for item in tmp_path.iterdir())
    assert doctor["ready"] is False and doctor["status"] == "MISSING"
    assert doctor["mutations_performed"] is False
    assert plan["network_access_performed"] is False
    assert plan["storage_gate"] is True
    assert before == after
    assert not cache.exists()


def test_adoption_requires_exact_consent_before_any_mutation(tmp_path: Path) -> None:
    candidate, blobs = _candidate(tmp_path)
    cache = tmp_path / "cache"
    with pytest.raises(GenerativeModelError, match="consentimento literal"):
        adopt_candidate(candidate, cache, consent="sim", fetcher=_fetcher(blobs))
    assert not cache.exists()


def test_adoption_is_transactional_and_doctor_verifies_every_file(tmp_path: Path) -> None:
    candidate, blobs = _candidate(tmp_path)
    cache = tmp_path / "cache"
    report = adopt_candidate(
        candidate,
        cache,
        consent=candidate.consent_phrase,
        fetcher=_fetcher(blobs),
    )
    assert report["ready"] is True
    assert Path(report["model_file"]).read_bytes() == blobs[candidate.model.url]
    assert Path(report["runtime_executable"]).name == "llama-server.exe"
    assert not tuple(cache.glob(".staging-*"))
    assert not tuple(cache.rglob("runtime.zip"))
    model = Path(report["model_file"])
    model.write_bytes(b"tampered")
    invalid = adoption_doctor(candidate, cache)
    assert invalid["ready"] is False
    assert invalid["status"] == "INVALID"


def test_zip_path_traversal_is_rejected_and_staging_is_removed(tmp_path: Path) -> None:
    candidate, blobs = _candidate(tmp_path, traversal=True)
    cache = tmp_path / "cache"
    with pytest.raises(GenerativeModelError, match="path traversal"):
        adopt_candidate(
            candidate,
            cache,
            consent=candidate.consent_phrase,
            fetcher=_fetcher(blobs),
        )
    assert not (tmp_path / "escape.txt").exists()
    assert not tuple(cache.glob(".staging-*"))


@pytest.mark.parametrize("archive_kind", ["reserved", "symlink"])
def test_windows_device_names_and_zip_symlinks_are_rejected(
    tmp_path: Path, archive_kind: str
) -> None:
    candidate, blobs = _candidate(
        tmp_path,
        reserved=archive_kind == "reserved",
        symlink=archive_kind == "symlink",
    )
    cache = tmp_path / "cache"
    expected = "device name" if archive_kind == "reserved" else "symlink"
    with pytest.raises(GenerativeModelError, match=expected):
        adopt_candidate(
            candidate,
            cache,
            consent=candidate.consent_phrase,
            fetcher=_fetcher(blobs),
        )
    assert not tuple(cache.glob(".staging-*"))


def test_existing_unverified_target_is_never_overwritten(tmp_path: Path) -> None:
    candidate, blobs = _candidate(tmp_path)
    cache = tmp_path / "cache"
    target = cache / candidate.candidate_id
    target.mkdir(parents=True)
    (target / "owner-data.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(GenerativeModelError, match="overwrite negado"):
        adopt_candidate(
            candidate,
            cache,
            consent=candidate.consent_phrase,
            fetcher=_fetcher(blobs),
        )
    assert (target / "owner-data.txt").read_text(encoding="utf-8") == "preserve"


def test_malformed_candidate_and_external_host_fail_closed(tmp_path: Path) -> None:
    candidate, _ = _candidate(tmp_path)
    payload = candidate.payload
    payload["model"]["url"] = "https://example.com/model.gguf"
    path = tmp_path / "external.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GenerativeModelError, match="origem não autorizada"):
        GenerativeCandidate.load(path)
