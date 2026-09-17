from __future__ import annotations

import os
from pathlib import Path

import pytest

from casulo.product.guide_continuity import ConstraintStrength, QuestionCandidate, RecordKind
from casulo.product.living_memory import TestSecretBox
from casulo.product.platform_contracts import LocalStorage
from casulo_owner.t85_continuity import ContinuityServiceError, T85ContinuityService
from casulo.t.productive import ProductiveTError


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime")
POLICY = ROOT / "private/casulo-owner/t-v2/guide-context-policy.t"


class FixedClock:
    def __init__(self) -> None:
        self.sequence = 0

    def monotonic_ns(self) -> int:
        return self.sequence

    def utc_timestamp(self) -> str:
        self.sequence += 1
        return f"2026-08-14T23:{self.sequence // 60:02d}:{self.sequence % 60:02d}Z"


def service(tmp_path: Path) -> T85ContinuityService:
    tcap = T85ContinuityService.build_policy(POLICY, tmp_path / "policy.tcap")
    return T85ContinuityService(
        tmp_path / "profile", clock=FixedClock(), secret_box=TestSecretBox(),
        t_runtime=RUNTIME, tcap=tcap, allow_test_encryption=True,
    )


def test_journal_reboot_project_isolation_and_t_context_policy(tmp_path: Path) -> None:
    first = service(tmp_path)
    for project in ("alpha", "beta", "gamma"):
        first.open_project(project, source_event_id=f"human:open:{project}")
        first.add_constraint(
            constraint_id=f"{project}:owner", project_id=project, key="authority",
            statement=f"{project}: confirmação humana é obrigatória.", strength=ConstraintStrength.HARD,
            source_event_ids=(f"human:constraint:{project}",),
        )
        first.record(
            record_id=f"{project}:decision", project_id=project, kind=RecordKind.DECISION,
            text=f"{project}: decisão exclusiva do projeto.", source_event_ids=(f"human:decision:{project}",), criticality=10,
        )
    selection = first.select_context(project_id="beta", query="decisão", budget_chars=4096)
    assert selection.decision == "SELECT"
    assert [item.ref_id for item in selection.directive.context_items] == ["beta:decision"]
    state_hash = first.kernel.state_sha256
    event_count = len(first.kernel.event_log)
    first.close()

    reopened = service(tmp_path)
    assert reopened.kernel.state_sha256 == state_hash
    assert len(reopened.kernel.event_log) == event_count
    assert reopened.select_context(project_id="gamma", query="decisão", budget_chars=4096).decision == "SELECT"
    assert all("alpha" not in item.text and "beta" not in item.text for item in reopened.kernel.directive(project_id="gamma", query="decisão", budget_chars=4096).context_items)
    reopened.close()


def test_conflict_is_explicit_and_supersession_keeps_history(tmp_path: Path) -> None:
    instance = service(tmp_path)
    instance.open_project("alpha", source_event_id="human:open")
    instance.record(record_id="alpha:v1", project_id="alpha", kind=RecordKind.DECISION, text="usar âmbar", source_event_ids=("human:v1",), criticality=9)
    instance.supersede(project_id="alpha", previous_record_id="alpha:v1", new_record_id="alpha:v2", text="usar azul profundo", human_event_id="human:v2")
    instance.add_constraint(constraint_id="alpha:offline", project_id="alpha", key="network", statement="offline", strength=ConstraintStrength.HARD, source_event_ids=("human:c1",))
    instance.add_constraint(constraint_id="alpha:online", project_id="alpha", key="network", statement="online", strength=ConstraintStrength.HARD, source_event_ids=("human:c2",))
    selection = instance.select_context(
        project_id="alpha", query="rede", budget_chars=4096,
        questions=(QuestionCandidate("resolve-network", "Offline ou online?", 1.0, 0.0, 0.0, True),),
    )
    assert selection.decision == "ASK_HUMAN"
    assert selection.directive.conflicts == ("online",)
    exported = instance.memory.export().decode("utf-8")
    assert "alpha:v1" in exported and "alpha:v2" in exported and "SUPERSESSION" in exported
    instance.close()


def test_single_writer_and_crash_debris_recovery(tmp_path: Path) -> None:
    first = service(tmp_path)
    with pytest.raises(ContinuityServiceError, match="writer ativo"):
        service(tmp_path)
    first.open_project("alpha", source_event_id="human:open")
    storage = LocalStorage(tmp_path / "profile/living-memory")
    storage.write_atomic("memory/events/.interrupted.json.dpapi.tmp", b"partial")
    first.close()
    reopened = service(tmp_path)
    assert reopened.kernel.snapshot()["projects"] == ["alpha"]
    assert storage.read("memory/events/.interrupted.json.dpapi.tmp") == b"partial"
    reopened.close()


def test_compaction_is_non_destructive_and_delete_needs_exact_consent(tmp_path: Path) -> None:
    instance = service(tmp_path)
    instance.open_project("alpha", source_event_id="human:open")
    count = len(instance.memory.events)
    receipt = instance.compact("ts8-checkpoint")
    assert receipt["events_preserved"] == count
    assert receipt["canonical_events_deleted"] == 0
    assert len(instance.memory.events) == count
    with pytest.raises(Exception, match="confirmação"):
        instance.memory.delete_all("sim")
    instance.close()


def test_t_policy_cancellation_is_fail_closed(tmp_path: Path) -> None:
    instance = service(tmp_path)
    instance.open_project("alpha", source_event_id="human:open")
    with pytest.raises(ContinuityServiceError, match="CANCELLED"):
        instance.select_context(project_id="alpha", query="x", budget_chars=1024, cancelled=True)
    instance.close()


def test_productive_runtime_rejects_ntfs_ads_call_id(tmp_path: Path) -> None:
    instance = service(tmp_path)
    with pytest.raises(ProductiveTError, match="call_id"):
        instance.executor.execute(
            "owner.guide.context_policy", "decide",
            {"project_match": True, "budget_valid": True, "mandatory_preserved": True, "ambiguity_present": False, "human_resolution_present": False, "cancelled": False},
            call_id="context:ads", surface_id="memory_governance", scope_id="project:alpha",
        )
    assert not (tmp_path / "profile/t-context-receipts/context").exists()
    instance.close()
