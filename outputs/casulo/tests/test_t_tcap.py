from __future__ import annotations

import json

import pytest

from casulo.t.resource import ResourceContract, SemanticClass
from casulo.t.tcap import TCAP_HEADER, TcapError, TcapSegment, build_tcap, parse_tcap


def contract() -> ResourceContract:
    return ResourceContract(
        memory_limit_bytes=1 << 20,
        arena_bytes=1 << 18,
        max_threads=1,
        semantic_class=SemanticClass.FLOW,
        deterministic=True,
        numerical_precision="float64",
        permissions=("memory", "console"),
        quality_definition={"protocol": "casulo-equivalence/1", "max_abs": 1e-12},
        residual_routing={"audit": "ATTRACTOR_AUDIT", "invalid": "QUARANTINE"},
    )


def artifact() -> bytes:
    return build_tcap(
        segments=(TcapSegment("code", b"\x90\xc3", "rx"), TcapSegment("ir", b"{}", "r")),
        target="x86_64-casulo-none",
        abi="casulo-syscall/0.1",
        entry_segment="code",
        entry_offset=0,
        compiler={"name": "casulo-t", "version": "0.1", "commit": "df12e916"},
        resource_contract=contract(),
    )


def test_tcap_is_deterministic_and_round_trips() -> None:
    first = artifact()
    second = artifact()
    assert first == second
    parsed = parse_tcap(first)
    assert parsed.raw == first
    assert [item.name for item in parsed.segments] == ["code", "ir"]
    assert parsed.manifest["energy"] == {"status": "unavailable", "joules": None}


@pytest.mark.parametrize("cut", [0, 1, TCAP_HEADER.size - 1, TCAP_HEADER.size, -1])
def test_truncation_is_rejected(cut: int) -> None:
    data = artifact()
    truncated = data[:cut] if cut >= 0 else data[:cut]
    with pytest.raises(TcapError):
        parse_tcap(truncated)


def test_segment_corruption_is_rejected() -> None:
    data = bytearray(artifact())
    data[-1] ^= 0x01
    with pytest.raises(TcapError, match="hash mismatch"):
        parse_tcap(bytes(data))


def test_wx_duplicate_names_and_invalid_entry_are_rejected() -> None:
    common = dict(
        target="x86_64-casulo-none", abi="casulo-syscall/0.1",
        compiler={"name": "casulo-t", "version": "0.1", "commit": "df12e916"},
        resource_contract=contract(),
    )
    with pytest.raises(TcapError, match=r"W\+X"):
        build_tcap(segments=(TcapSegment("code", b"x", "rwx"),), entry_segment="code", entry_offset=0, **common)
    duplicate = (TcapSegment("code", b"a", "rx"), TcapSegment("code", b"b", "r"))
    with pytest.raises(TcapError, match="duplicate"):
        build_tcap(segments=duplicate, entry_segment="code", entry_offset=0, **common)
    with pytest.raises(TcapError, match="entry point"):
        build_tcap(segments=(TcapSegment("data", b"x", "r"),), entry_segment="data", entry_offset=0, **common)


def test_noncanonical_or_duplicate_json_is_rejected() -> None:
    data = artifact()
    _, _, _, manifest_len, _, payload_offset, _ = TCAP_HEADER.unpack_from(data)
    manifest = json.loads(data[TCAP_HEADER.size : TCAP_HEADER.size + manifest_len])
    noncanonical = json.dumps(manifest, indent=1).encode()
    assert len(noncanonical) > manifest_len
    broken_header = TCAP_HEADER.pack(b"TCAP", 1, 0, len(noncanonical), 2, payload_offset, len(data))
    broken = broken_header + noncanonical + data[TCAP_HEADER.size + len(noncanonical) :]
    with pytest.raises(TcapError):
        parse_tcap(broken)
