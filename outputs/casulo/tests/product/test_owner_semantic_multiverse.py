from __future__ import annotations

from dataclasses import replace

from casulo.product.semantic_multiverse import CancellationToken
from casulo_owner.local_model_runtime import StochasticTrace
from casulo_owner.semantic_multiverse import GenerativeRouteProposal, OwnerSemanticMultiverse


def proposal() -> GenerativeRouteProposal:
    trace = StochasticTrace(
        "semantic-route-test", "qwen3-4b", "0" * 64, "planning-v1", None,
        "1" * 64, "2" * 64, 12, "stop", 1, 2, False, False,
    )
    return GenerativeRouteProposal(
        "semantic-route-test",
        ("intencao", "sinais", "engenharia", "diagnostico", "interface", "materializacao"),
        "A rota preserva intenção, processa sinais, verifica engenharia e só então materializa.",
        trace,
        "3" * 64,
    )


def test_owner_slice_visits_six_with_strict_hot_subset_receipts_and_reboot(tmp_path) -> None:
    runtime = OwnerSemanticMultiverse(tmp_path / "owner", hot_limit=3, memory_limit_bytes=48 * 1024 * 1024)
    result = runtime.execute(
        proposal(), idea="Agente diagnóstico para sinais de uma bomba", constraints=("sem rede", "somente simulação"),
        confirmed=True, cancellation=CancellationToken(),
    )
    assert result["universes_visited"] == list(proposal().route)
    assert result["strict_hot_subset"]
    assert result["hot_at_completion"] == ["materializacao"]
    assert len(result["transition_receipts"]) == 5
    assert all(receipt["committed"] for receipt in result["transition_receipts"])
    assert all(receipt["bytes_transferred"] <= receipt["bytes_read"] for receipt in result["transition_receipts"])
    assert result["cloud"] == "RELEASE_LOCKED" and result["usb"] == "PROHIBITED"
    assert runtime.render(result, tmp_path / "visual").is_file()
    reboot = runtime.reboot()
    assert reboot["sessions"] == 1 and reboot["hot_after_reboot"] == [] and not reboot["false_hot_persistence"]
    gc = runtime.gc_plan()
    assert gc["candidates"] == [] and not gc["material_delete_executed"]


def test_unconfirmed_or_cancelled_route_publishes_no_session(tmp_path) -> None:
    root = tmp_path / "owner"
    runtime = OwnerSemanticMultiverse(root)
    try:
        runtime.execute(proposal(), idea="x", constraints=("safe",), confirmed=False, cancellation=CancellationToken())
    except RuntimeError as error:
        assert "não confirmada" in str(error)
    token = CancellationToken(True)
    try:
        runtime.execute(proposal(), idea="x", constraints=("safe",), confirmed=True, cancellation=token)
    except Exception as error:
        assert "SM401" in str(error)
    assert not (root / "sessions").exists()


def test_twenty_sessions_share_bases_and_tcap_without_duplicate_blobs(tmp_path) -> None:
    runtime = OwnerSemanticMultiverse(tmp_path / "owner")
    base = proposal()
    for index in range(20):
        runtime.execute(
            replace(base, operation_id=f"semantic-route-{index}", rationale=f"Rota distinta da sessão {index}, preservando as restrições e a proveniência."),
            idea=f"Agente diagnóstico singular sessão {index}", constraints=("sem rede",), confirmed=True,
            cancellation=CancellationToken(),
        )
    assert len(tuple((runtime.root / "sessions").glob("*.json"))) == 20
    assert len(tuple(runtime.store.blobs.iterdir())) == 7  # seis bases + um TCAP deduplicado
    assert len(tuple(runtime.store.deltas.iterdir())) == 20
    plan = runtime.gc_plan()
    assert plan["candidates"] == [] and plan["protected_objects_untouched"]
