from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from casulo.livelab.energy_v1.hwinfo_campaign import (
    EAGER_IMPLEMENTATION,
    HWiNFOLiveTail,
    PAIR_COUNT,
    TCAP_IMPLEMENTATION,
    _completed_pairs,
    _schedule,
    allocate_campaign_id,
    initialize_campaign,
    verify_hwinfo_seal,
)
from casulo.livelab.energy_v1.schemas import sha256_file, write_json
from casulo.livelab.energy_v1.hwinfo_workers import build_native_worker


ROOT = Path(__file__).resolve().parents[1]
TCAP = ROOT / "release" / "FloodSurrogate.tcap"


def _communicate(command: list[str]) -> tuple[dict, dict]:
    completed = subprocess.run(
        command,
        input="RUN 1\nSTOP\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    lines = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    return lines[0], lines[1]


def test_schedule_is_frozen_balanced_ab_ba() -> None:
    schedule = _schedule()
    assert len(schedule) == PAIR_COUNT == 21
    assert schedule[0]["order"] == [TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION]
    assert schedule[1]["order"] == [EAGER_IMPLEMENTATION, TCAP_IMPLEMENTATION]
    assert len({item["pair_id"] for item in schedule}) == PAIR_COUNT


def test_live_tail_reads_only_latest_complete_row_and_tracks_append(tmp_path: Path) -> None:
    source = tmp_path / "live.csv"
    source.write_text(
        "Date,Time,CPU Package Power [W],CPU Package [C],Thermal Throttling [Yes/No]\n"
        "07.08.2026,12:00:00.000,5,45,No\n",
        encoding="utf-8",
        newline="\n",
    )
    reader = HWiNFOLiveTail(source, tail_bytes=128)
    reader.initialize()
    with source.open("ab") as handle:
        handle.write(b"07.08.2026,12:00:00.500,6,46,No\n")
        handle.write(b"07.08.2026,12:00:01.000,7")
    header, values, timestamp, size = reader.read_latest()
    assert header[2] == "CPU Package Power [W]"
    assert values[2:] == ("6", "46", "No")
    assert timestamp.microsecond == 500_000
    assert size == source.stat().st_size

    with source.open("ab") as handle:
        handle.write(b",47,No\n")
    _, values, timestamp, _ = reader.read_latest()
    assert values[2:] == ("7", "47", "No")
    assert timestamp.second == 1


def test_sealed_campaign_gets_sequential_suffix(tmp_path: Path) -> None:
    first = tmp_path / "campaign"
    first.mkdir()
    write_json(first / "MANIFEST.json", {"files": []})
    assert allocate_campaign_id(tmp_path, "campaign") == "campaign-02"
    (tmp_path / "campaign-02").mkdir()
    assert allocate_campaign_id(tmp_path, "campaign") == "campaign-03"


@pytest.mark.skipif(not TCAP.is_file(), reason="real FloodSurrogate TCAP required")
def test_h0_uses_actual_bounded_snapshot_and_detects_old_folder_name(tmp_path: Path) -> None:
    source_dir = tmp_path / "2026-08-02-old-session"
    source_dir.mkdir()
    csv_path = source_dir / "live.csv"
    csv_path.write_text(
        "Date,Time,CPU Package Power [W]\n"
        "07.08.2026,12:00:00.000,5.0\n"
        "07.08.2026,12:00:02.000,6.0\n"
        "07.08.2026,12:00:04.000,7.0\n",
        encoding="utf-8",
        newline="\n",
    )
    campaign = initialize_campaign(
        tmp_path / "energy",
        csv_path,
        TCAP,
        "new",
        _allow_bounded_canary_for_nonperformance_test=True,
    )
    capture = json.loads((campaign / "h0_initial_capture.json").read_text(encoding="utf-8"))
    assert capture["byte_offset"] == csv_path.stat().st_size
    assert capture["sha256_snapshot"] == sha256_file(csv_path)
    assert capture["source_history"]["logger_restarted_or_overwrote_older_named_file"] is True


@pytest.mark.skipif(not TCAP.is_file(), reason="real FloodSurrogate TCAP required")
def test_energy_campaign_rejects_the_eight_record_correctness_canary(tmp_path: Path) -> None:
    """Regression: the bounded TCAP canary is not a 1,024-record training unit."""

    csv_path = tmp_path / "live.csv"
    csv_path.write_text(
        "Date,Time,CPU Package Power [W]\n"
        "08.08.2026,12:00:00.000,5.0\n"
        "08.08.2026,12:00:00.250,6.0\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="1,024-record.*work unit"):
        initialize_campaign(tmp_path / "energy", csv_path, TCAP, "forensic-regression")


def test_transactional_resume_counts_only_complete_pairs(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_json(raw / "pair-01-a.json", {"pair_id": "pair-01", "implementation": TCAP_IMPLEMENTATION, "accepted": True})
    assert _completed_pairs(tmp_path) == set()
    write_json(raw / "pair-01-b.json", {"pair_id": "pair-01", "implementation": EAGER_IMPLEMENTATION, "accepted": True})
    write_json(raw / "pair-02-a.json", {"pair_id": "pair-02", "implementation": TCAP_IMPLEMENTATION, "accepted": False})
    assert _completed_pairs(tmp_path) == {"pair-01"}


def test_seal_verifier_rejects_tampering(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    write_json(payload, {"physical": True})
    item = {"path": "payload.json", "bytes": payload.stat().st_size, "sha256": sha256_file(payload)}
    write_json(tmp_path / "MANIFEST.json", {"files": [item]})
    manifest_hash = sha256_file(tmp_path / "MANIFEST.json")
    (tmp_path / "SHA256SUMS").write_text(
        f"{item['sha256']}  payload.json\n{manifest_hash}  MANIFEST.json\n",
        encoding="ascii",
    )
    assert verify_hwinfo_seal(tmp_path)["status"] == "PASS"
    payload.write_text("tampered", encoding="utf-8")
    assert verify_hwinfo_seal(tmp_path)["status"] == "FAIL"


@pytest.mark.skipif(sys.platform != "win32" or not TCAP.is_file(), reason="real Windows TCAP worker required")
def test_native_worker_executes_real_tcap_and_resets(tmp_path: Path) -> None:
    build = build_native_worker(TCAP, tmp_path)
    ready, result = _communicate([build["executable"]])
    assert ready["event"] == "READY"
    assert result["status"] == "PASS"
    assert result["K"] == 1
    assert result["epochs_per_training"] == 400
    assert result["max_abs_parameter_error_vs_frozen_oracle"] == 0


@pytest.mark.skipif(not TCAP.is_file(), reason="real FloodSurrogate TCAP required")
def test_eager_worker_matches_frozen_oracle() -> None:
    ready, result = _communicate([
        sys.executable,
        "-m",
        "casulo.livelab.energy_v1.hwinfo_workers",
        "--eager-worker",
        "--tcap",
        str(TCAP),
        "--threads",
        "1",
    ])
    assert ready["threads"] == 1
    assert result["status"] == "PASS"
    assert result["epochs_per_training"] == 400
    assert result["max_abs_parameter_error_vs_frozen_oracle"] <= 1e-9
