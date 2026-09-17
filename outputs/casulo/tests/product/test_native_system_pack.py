from __future__ import annotations

import pytest

from tools.build_native_system_pack import KINDS, build, build_from_paths, parse, parse_file


def test_system_pack_roundtrip_and_hashes() -> None:
    blob = build([
        (KINDS["BOOTSTRAP_TCAP"], b"tcap"),
        (KINDS["UX_CONTRACT"], b"schema"),
        (KINDS["MODEL_GGUF_PROBE"], b"GGUF-probe"),
    ])
    parsed = parse(blob)
    assert [entry["kind"] for entry in parsed] == [1, 2, 4]
    assert [entry["bytes"] for entry in parsed] == [4, 6, 10]


def test_system_pack_roundtrips_native_creation_contracts() -> None:
    blob = build([
        (KINDS["NATIVE_CREATION_PROMPT"], b"prompt"),
        (KINDS["NATIVE_CREATION_ARTIFACT"], b"artifact"),
        (KINDS["NATIVE_CREATION_ACCEPTANCE"], b"acceptance"),
    ])
    parsed = parse(blob)
    assert [entry["kind"] for entry in parsed] == [6, 7, 8]
    assert [entry["bytes"] for entry in parsed] == [6, 8, 10]


def test_system_pack_roundtrips_physical_model_entry() -> None:
    blob = build([
        (KINDS["BOOTSTRAP_TCAP"], b"tcap"),
        (KINDS["NATIVE_MODEL_GGUF"], b"GGUF-physical-model"),
    ])
    parsed = parse(blob)
    assert [entry["kind"] for entry in parsed] == [1, 9]
    assert parsed[1]["bytes"] == 19


def test_streaming_system_pack_does_not_materialize_sources(tmp_path) -> None:
    tcap = tmp_path / "bootstrap.tcap"
    model = tmp_path / "model.gguf"
    output = tmp_path / "physical.cspk"
    tcap.write_bytes(b"tcap")
    model.write_bytes(b"GGUF" + b"x" * (2 * 1024 * 1024))

    manifest = build_from_paths(
        output,
        [(KINDS["BOOTSTRAP_TCAP"], tcap), (KINDS["NATIVE_MODEL_GGUF"], model)],
    )

    assert manifest[1]["bytes"] == model.stat().st_size
    assert parse_file(output) == manifest
    assert output.stat().st_size == 16 + 2 * 64 + tcap.stat().st_size + model.stat().st_size


def test_system_pack_rejects_corruption_and_duplicates() -> None:
    with pytest.raises(ValueError, match="unique"):
        build([(1, b"a"), (1, b"b")])
    blob = bytearray(build([(1, b"tcap")]))
    blob[-1] ^= 1
    with pytest.raises(ValueError, match="hash"):
        parse(bytes(blob))
