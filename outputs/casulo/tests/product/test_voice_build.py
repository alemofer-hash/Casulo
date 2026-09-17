from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from casulo.product.platform_contracts import PlatformError
from casulo.product.voice_build import build_voice_bridge
from casulo.product.voice_candidate import VoiceCacheInspection, VoiceCandidate


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release/voice-candidates/whisper-cpp-v1.9.2.json"


def test_build_refuses_missing_cache_before_creating_directories(tmp_path) -> None:
    cache = tmp_path / "absent"
    with pytest.raises(PlatformError, match="source ASR"):
        build_voice_bridge(VoiceCandidate.load(MANIFEST), cache, ROOT)
    assert not cache.exists()


def test_build_uses_argv_without_download_and_seals_binary(tmp_path, monkeypatch) -> None:
    candidate = VoiceCandidate.load(MANIFEST)
    cache = tmp_path / "voice"
    source = cache / "sources/whisper/source"
    source.mkdir(parents=True)
    (source / "CMakeLists.txt").write_text("project(fake)", encoding="utf-8")
    bridge = cache / "bin/casulo_whisper_bridge.dll"
    inspection = VoiceCacheInspection(
        cache_root=cache,
        source_dir=source,
        source_receipt=cache / "SOURCE.json",
        model_path=cache / "model.bin",
        bridge_path=bridge,
        source_verified=True,
        model_present=True,
        model_verified=True,
        bridge_present=False,
        free_bytes=1_000_000_000,
        ready=False,
    )
    monkeypatch.setattr("casulo.product.voice_build.inspect_voice_cache", lambda *args: inspection)
    monkeypatch.setattr("casulo.product.voice_build.shutil.which", lambda name: name)
    commands: list[list[str]] = []

    def fake_runner(argv, **kwargs):
        commands.append(list(argv))
        if "--build" in argv:
            bridge.parent.mkdir(parents=True, exist_ok=True)
            bridge.write_bytes(b"first-party-bridge")
        return subprocess.CompletedProcess(argv, 0, "", "")

    report = build_voice_bridge(candidate, cache, ROOT, runner=fake_runner)
    assert len(commands) == 2
    assert all(isinstance(command, list) for command in commands)
    assert report["download_performed"] is False
    assert report["bridge_sha256"] == hashlib.sha256(b"first-party-bridge").hexdigest()
    receipt = json.loads((cache / "BUILD.json").read_text(encoding="utf-8"))
    assert receipt["engine_commit"] == candidate.engine_commit


def test_first_party_bridge_compiles_against_narrow_c_api_stub(tmp_path) -> None:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("compilador C++ não disponível")
    include = tmp_path / "include"
    include.mkdir()
    (include / "whisper.h").write_text(
        textwrap.dedent(
            """
            #pragma once
            #include <cstdint>
            struct whisper_context {};
            struct whisper_context_params { bool use_gpu; };
            enum whisper_sampling_strategy { WHISPER_SAMPLING_GREEDY };
            struct whisper_full_params {
                int n_threads; const char * language;
                bool detect_language, translate, no_context, no_timestamps;
                bool single_segment, print_special, print_progress;
                bool print_realtime, print_timestamps;
            };
            extern "C" {
            whisper_context_params whisper_context_default_params();
            whisper_context * whisper_init_from_file_with_params(const char *, whisper_context_params);
            int whisper_is_multilingual(whisper_context *);
            void whisper_free(whisper_context *);
            const char * whisper_version();
            whisper_full_params whisper_full_default_params(whisper_sampling_strategy);
            int whisper_full(whisper_context *, whisper_full_params, const float *, int);
            int whisper_full_n_segments(whisper_context *);
            const char * whisper_full_get_segment_text(whisper_context *, int);
            }
            """
        ),
        encoding="utf-8",
    )
    stub = tmp_path / "stub.cpp"
    stub.write_text(
        textwrap.dedent(
            """
            #include "whisper.h"
            whisper_context_params whisper_context_default_params(){ return {false}; }
            whisper_context * whisper_init_from_file_with_params(const char *, whisper_context_params){ static whisper_context c; return &c; }
            int whisper_is_multilingual(whisper_context *){ return 1; }
            void whisper_free(whisper_context *){}
            const char * whisper_version(){ return "stub"; }
            whisper_full_params whisper_full_default_params(whisper_sampling_strategy){ return {}; }
            int whisper_full(whisper_context *, whisper_full_params, const float *, int){ return 0; }
            int whisper_full_n_segments(whisper_context *){ return 0; }
            const char * whisper_full_get_segment_text(whisper_context *, int){ return ""; }
            """
        ),
        encoding="utf-8",
    )
    output = tmp_path / "bridge.dll"
    result = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-shared",
            "-DCASULO_WHISPER_BUILD=1",
            "-I",
            str(include),
            str(ROOT / "native/voice/casulo_whisper_bridge.cpp"),
            str(stub),
            "-o",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert output.is_file()


def test_cmake_emits_the_cross_toolchain_bridge_name_expected_by_doctor() -> None:
    cmake = (ROOT / "native/voice/CMakeLists.txt").read_text(encoding="utf-8")
    assert 'PREFIX ""' in cmake
    assert 'OUTPUT_NAME "casulo_whisper_bridge"' in cmake
    assert "-static-libgcc" in cmake
    assert "-static-libstdc++" in cmake
