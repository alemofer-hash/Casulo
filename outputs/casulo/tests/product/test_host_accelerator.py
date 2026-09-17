from __future__ import annotations

import hashlib

import pytest

from casulo.product.host_accelerator import (
    AcceleratorFrame,
    AcceleratorHandshake,
    AcceleratorProtocolError,
    HostAcceleratorService,
)


def handshake() -> AcceleratorHandshake:
    h = hashlib.sha256(b"build").hexdigest()
    return AcceleratorHandshake("casulo-host-accelerator/1.0", "nonce-0123456789", h, h, h, h)


def test_bounded_frame_round_trip_and_replay_denial() -> None:
    service = HostAcceleratorService(handshake(), lambda kind, payload: b'{"status":"ok"}')
    frame = AcceleratorFrame.create("guide.turn", "request-1", 1, b'{"text":"ola"}', 200)
    output, receipt = service.handle(frame, now_monotonic_ns=100)
    assert output == b'{"status":"ok"}'
    assert receipt.status == "PASS"
    with pytest.raises(AcceleratorProtocolError, match="replay"):
        service.handle(frame, now_monotonic_ns=100)


@pytest.mark.parametrize("payload", [b'{"command":"cmd.exe"}', b'{"host_path":"C:/"}', b'{"device":"PhysicalDrive0"}'])
def test_arbitrary_host_authority_is_denied(payload: bytes) -> None:
    service = HostAcceleratorService(handshake(), lambda kind, value: value)
    frame = AcceleratorFrame.create("guide.turn", hashlib.sha256(payload).hexdigest(), 1, payload, 200)
    with pytest.raises(AcceleratorProtocolError, match="proibido"):
        service.handle(frame, now_monotonic_ns=100)


def test_cancel_deadline_hash_size_and_type_fail_closed() -> None:
    service = HostAcceleratorService(handshake(), lambda kind, value: value)
    service.cancel_through(2)
    stale = AcceleratorFrame.create("guide.turn", "stale", 2, b'{"text":"x"}', 200)
    with pytest.raises(AcceleratorProtocolError, match="stale"):
        service.handle(stale, now_monotonic_ns=100)
    expired = AcceleratorFrame.create("guide.turn", "expired", 3, b'{"text":"x"}', 50)
    with pytest.raises(AcceleratorProtocolError, match="deadline"):
        service.handle(expired, now_monotonic_ns=100)
    bad_hash = AcceleratorFrame("guide.turn", "hash", 3, b'{}', "0" * 64, 200)
    with pytest.raises(AcceleratorProtocolError, match="hash"):
        service.handle(bad_hash, now_monotonic_ns=100)
    wrong = AcceleratorFrame.create("filesystem.read", "wrong", 3, b'{}', 200)
    with pytest.raises(AcceleratorProtocolError, match="allowlist"):
        service.handle(wrong, now_monotonic_ns=100)
