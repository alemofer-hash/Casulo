from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from casulo.product.discovery_session import DiscoverySessionError, DiscoverySessionRecorder, verify_chain
from tools.monday_discovery import analyse_campaign, analyse_session


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "product-demos/human-proof/monday-discovery-2026-08-17-attempt1/START_MONDAY_DISCOVERY.vbs"
FAST_LAUNCHER = ROOT / "product-demos/human-proof/monday-discovery-fast-2026-08-18-attempt1/START_MONDAY_DISCOVERY_FAST.vbs"
ARC9_LAUNCHER = ROOT / "product-demos/human-proof/monday-arc-pleasant-2026-08-18-attempt1/START_CASULO_ARC9.vbs"


def test_automated_and_human_sources_are_separate_and_chained(tmp_path: Path) -> None:
    recorder = DiscoverySessionRecorder(tmp_path / "session", session_id="m1:test", release_manifest_sha256="a" * 64)
    event = recorder.record_automated("USER_TURN", {"turn": 1, "input_sha256": "b" * 64, "input_chars": 22})
    note = recorder.record_human_note(
        "A resposta pareceu distante da intenção.",
        category="INTENT_ARTIFACT_DIVERGENCE",
        severity="P1",
        source_event_ids=(event["event_id"],),
    )
    recorder.record_automated("PRESENCE_READY", {"output_sha256": "c" * 64})
    recorder.record_automated("SUBSTANTIVE_RESPONSE", {"turn": 1, "response_sha256": "d" * 64, "response_chars": 81})
    summary = recorder.finalize(outcome="TEST", process_exit_code=0)
    assert summary["chains"]["automated"]["valid"] is True
    assert summary["chains"]["human"]["valid"] is True
    assert note["provenance"] == "HUMAN_OPINION_GUILHERME"
    assert "A resposta" not in recorder.automated_path.read_text(encoding="utf-8")
    assert "A resposta" in recorder.human_path.read_text(encoding="utf-8")
    assert summary["privacy"] == {
        "raw_audio_persisted": False,
        "transcripts_persisted_by_observer": False,
        "user_content_persisted_by_observer": False,
        "secrets_included": False,
    }


def test_automatic_observer_rejects_content_and_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "session"
    recorder = DiscoverySessionRecorder(root, session_id="m1:privacy", release_manifest_sha256="a" * 64)
    with pytest.raises(DiscoverySessionError, match="sensivel"):
        recorder.record_automated("BAD_EVENT", {"transcript": "nao pode persistir"})
    with pytest.raises(DiscoverySessionError, match="overwrite"):
        DiscoverySessionRecorder(root, session_id="m1:again", release_manifest_sha256="a" * 64)


def test_chain_tamper_is_detected(tmp_path: Path) -> None:
    recorder = DiscoverySessionRecorder(tmp_path / "session", session_id="m1:tamper", release_manifest_sha256="a" * 64)
    recorder.record_automated("SESSION_OPENED", {"mode": "TEST"})
    payload = recorder.automated_path.read_text(encoding="utf-8").replace('"mode":"TEST"', '"mode":"ALTERED"')
    recorder.automated_path.write_text(payload, encoding="utf-8", newline="\n")
    assert verify_chain(recorder.automated_path, hash_field="event_hash", previous_field="previous_hash")["valid"] is False


def test_voice_is_literal_consent_gated_and_launcher_parses() -> None:
    source = (ROOT / "tools/monday_discovery_session.pyw").read_text(encoding="utf-8")
    assert "AUTORIZO VOZ LOCAL POR 8 SEGUNDOS SEM SALVAR PCM" in source
    assert "TTS_SUPPRESSED_NO_LITERAL_CONSENT" in source
    assert "PHYSICAL_VOICE_CONSENT_DENIED" in source
    environment = os.environ.copy()
    environment["CASULO_MONDAY_DISCOVERY_DRY_RUN"] = "1"
    completed = subprocess.run(
        ["cscript.exe", "//nologo", str(LAUNCHER)],
        env=environment,
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace",
        check=False,
        shell=False,
    )
    assert completed.returncode == 0
    assert "CASULO_MONDAY_DISCOVERY_VBS_PARSE_PASS" in completed.stdout


def test_fast_discovery_launcher_is_explicit_and_keeps_original_profile_default() -> None:
    source = (ROOT / "tools/monday_discovery_session.pyw").read_text(encoding="utf-8")
    launcher = FAST_LAUNCHER.read_text(encoding="utf-8")
    assert '--dialogue-transport", choices=DIALOGUE_TRANSPORTS, default="vm-bridge"' in source
    assert "decode_ux_event" in source
    assert '"arc-stream"' in source
    assert "UxStreamValidator" in source
    assert "DISCOVERY_FAST_PATH_ACTIVE" in source
    assert "--dialogue-transport host-direct" in launcher
    assert '"--ui-mode",' in source and '"arc-stream",' in source
    assert "self.root.after(24 if self.dialogue_transport" in source
    environment = os.environ.copy()
    environment["CASULO_MONDAY_DISCOVERY_DRY_RUN"] = "1"
    completed = subprocess.run(
        ["cscript.exe", "//nologo", str(FAST_LAUNCHER)],
        env=environment,
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace",
        check=False,
        shell=False,
    )
    assert completed.returncode == 0
    assert "CASULO_MONDAY_DISCOVERY_FAST_VBS_PARSE_PASS" in completed.stdout


def test_session_metadata_never_claims_human_completion(tmp_path: Path) -> None:
    recorder = DiscoverySessionRecorder(tmp_path / "session", session_id="m1:pending", release_manifest_sha256="a" * 64)
    metadata = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    assert metadata["physical_voice_authorized"] is False
    assert metadata["raw_audio_persisted"] is False
    assert "human_proof_pass" not in metadata


def test_arc9_launcher_parses_and_surface_is_not_a_technical_dashboard() -> None:
    source = (ROOT / "tools/monday_discovery_session.pyw").read_text(encoding="utf-8")
    assert "_install_arc9_surface" in source
    assert "Pensando em voz alta" in source
    assert "Criando em background" in source
    assert "progress_percent" not in source
    assert "for child in self.root.winfo_children()" in source
    environment = os.environ.copy()
    environment["CASULO_MONDAY_DISCOVERY_DRY_RUN"] = "1"
    completed = subprocess.run(
        ["cscript.exe", "//nologo", str(ARC9_LAUNCHER)],
        env=environment,
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace",
        check=False,
        shell=False,
    )
    assert completed.returncode == 0
    assert "CASULO_ARC9_VBS_PARSE_PASS" in completed.stdout


def test_campaign_requires_reboot_pair_and_explicit_human_verdict(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    first = DiscoverySessionRecorder(campaign / "session-1", session_id="m1:session-1", release_manifest_sha256="a" * 64)
    first.record_automated("PRESENCE_READY", {"output_sha256": "b" * 64})
    first.finalize(outcome="REBOOT_REQUESTED", process_exit_code=0)
    assert analyse_session(campaign / "session-1")["state"] == "READY_FOR_GUILHERME_MONDAY_DISCOVERY_SESSION"

    second = DiscoverySessionRecorder(campaign / "session-2", session_id="m1:session-2", release_manifest_sha256="a" * 64)
    event = second.record_automated("REBOOT_RECALL_STATUS", {"output_sha256": "c" * 64})
    second.record_human_note(
        "Sessão concluída; estas são minhas observações finais.",
        category="SESSION_VERDICT",
        source_event_ids=(event["event_id"],),
    )
    second.finalize(outcome="CLOSED_BY_GUILHERME", process_exit_code=0)
    analysis = analyse_campaign(campaign)
    assert analysis["state"] == "MONDAY_FAILURE_ATLAS_COMPLETE"
    assert analysis["reboot_exercised"] is True
    assert analysis["human_session_verdict_present"] is True
