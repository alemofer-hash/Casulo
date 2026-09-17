from __future__ import annotations

import pytest

from casulo.product.discovery_transport import IncrementalLineFramer, completion_notice, deliver_dialogue


class FakeBridge:
    def __init__(self) -> None:
        self.calls = 0

    def bridge_boot(self, response, *, timeout: float, acceleration: str):
        self.calls += 1
        return {
            "answer": response(),
            "timeout": timeout,
            "acceleration": acceleration,
        }


def test_host_direct_delivers_once_without_dialogue_vm_boot() -> None:
    bridge = FakeBridge()
    providers = 0

    def provider() -> str:
        nonlocal providers
        providers += 1
        return "resposta incremental real"

    receipt = deliver_dialogue(transport="host-direct", controller=bridge, provider=provider)
    assert providers == 1
    assert bridge.calls == 0
    assert receipt == {
        "schema": "casulo.discovery-dialogue-delivery/1.0",
        "transport": "HOST_DIRECT",
        "answer_chars": 25,
        "vm_creation_gate_preserved": True,
        "scientific_or_release_proof": False,
    }


def test_release_dialogue_transport_retains_tcg_bridge() -> None:
    bridge = FakeBridge()
    receipt = deliver_dialogue(transport="vm-bridge", controller=bridge, provider=lambda: "selado")
    assert bridge.calls == 1
    assert receipt == {"answer": "selado", "timeout": 900, "acceleration": "tcg"}


def test_unknown_transport_and_empty_direct_answer_fail_closed() -> None:
    bridge = FakeBridge()
    with pytest.raises(ValueError, match="allowlist"):
        deliver_dialogue(transport="unknown", controller=bridge, provider=lambda: "x")
    with pytest.raises(ValueError, match="vazia"):
        deliver_dialogue(transport="host-direct", controller=bridge, provider=lambda: "  ")


def test_incremental_line_framer_never_requires_a_full_output_buffer() -> None:
    framer = IncrementalLineFramer()
    assert framer.feed("Cas") == ()
    assert framer.feed("ulo › primeira\nCasulo › seg") == ("Casulo › primeira\n",)
    assert framer.feed("unda\n") == ("Casulo › segunda\n",)
    assert framer.finish() == ()


def test_incremental_line_framer_preserves_final_partial_line() -> None:
    framer = IncrementalLineFramer()
    assert framer.feed("token sem newline") == ()
    assert framer.finish() == ("token sem newline",)


def test_only_observed_length_finish_reason_produces_limit_notice() -> None:
    assert completion_notice("stop") is None
    assert completion_notice("unknown") is None
    assert completion_notice(None) is None
    assert completion_notice("length") == (
        "Casulo status · RESPONSE_LIMIT_REACHED · resposta preservada; peça para continuar"
    )
