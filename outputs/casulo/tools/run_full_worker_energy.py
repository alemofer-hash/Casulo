"""Physical HWiNFO campaign for the complete FloodSurrogate worker.

The campaign is resumable and integrates only worker-emitted UTC windows.  It
never treats time, temperature, utilization, or logical counters as energy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from casulo.livelab.energy_v1.analysis import exact_sign_test, paired_bootstrap_ci
from casulo.livelab.energy_v1.full_workers import (
    EAGER_FULL_IMPLEMENTATION,
    TCAP_FULL_IMPLEMENTATION,
    build_full_native_worker,
    compare_results,
    create_receipts,
    parse_result_file,
    validate_full_tcap,
    validate_receipts,
)
from casulo.livelab.energy_v1.hwinfo import inspect_file, integrate_window
from casulo.livelab.energy_v1.hwinfo_campaign import _live_guard, _wait_for_bracketing_sample
from tools.run_full_worker_validation import (
    HARD_LIMIT_C,
    _parse_worker_stdout,
    _run_guarded,
    _sha256_file,
    _write_json,
)


DEFAULT_FULL = ROOT / "outputs/casulo/full-worker/2026-08-08-flood-full-worker-v1-r2"
DEFAULT_CSV = ROOT / "benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV"
DEFAULT_OUTPUT = ROOT / "outputs/casulo/energy/2026-08-08-g5-full-worker-hwinfo-energy"
PAIR_COUNT = 21
COMMON_K = 620
WINDOW_TCAP_K = 620
WINDOW_EAGER_K = 66
MINIMUM_SAMPLES = 60
MINIMUM_COVERAGE = 0.98
START_TARGET_C = 60.0
BOOTSTRAP_SEED = 20260808
BOOTSTRAP_RESAMPLES = 20_000


def _utc_from_ns(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1e9, timezone.utc)


def _wait_stable_start(
    csv_path: Path, *, target_c: float | None = None, seconds: float = 30.0, timeout: float = 1200.0
) -> dict[str, Any]:
    ceiling = START_TARGET_C if target_c is None else target_c + 1.0
    floor = None if target_c is None else target_c - 1.0
    deadline = time.monotonic() + timeout
    stable_since: datetime | None = None
    previous_stamp = None
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _live_guard(csv_path, during_load=False)
        temperature = last.get("temperature_c")
        if last.get("throttling") or (temperature or 0) >= HARD_LIMIT_C:
            raise RuntimeError("physical thermal guard: " + json.dumps(last))
        stamp_text = last.get("hwinfo_timestamp_utc")
        valid = (
            last.get("logger_live")
            and last.get("ac_connected") is True
            and temperature is not None
            and temperature <= ceiling
            and (floor is None or temperature >= floor)
        )
        if valid and stamp_text and stamp_text != previous_stamp:
            stamp = datetime.fromisoformat(stamp_text)
            if stable_since is None:
                stable_since = stamp
            if (stamp - stable_since).total_seconds() >= seconds:
                return last
            previous_stamp = stamp_text
        elif not valid:
            stable_since = None
        time.sleep(0.25)
    raise RuntimeError("stable-start timeout: " + json.dumps(last))


def _marker_window(path: Path) -> tuple[datetime, datetime]:
    values = {}
    for line in path.read_text(encoding="ascii").splitlines():
        name, raw = line.split()
        values[name] = int(raw)
    if set(values) != {"START", "END"} or values["END"] <= values["START"]:
        raise ValueError("worker marker file is invalid")
    return _utc_from_ns(values["START"]), _utc_from_ns(values["END"])


def _command(
    implementation: str,
    *,
    k: int,
    tcap: Path,
    worker: Path,
    dataset: Path,
    initializations: Path,
    result: Path,
    marker: Path,
) -> list[str]:
    if implementation == TCAP_FULL_IMPLEMENTATION:
        return [str(worker), str(dataset), str(initializations), "0", str(k), str(result), str(marker)]
    return [
        sys.executable,
        "-m",
        "casulo.livelab.energy_v1.full_workers",
        "--eager",
        "--tcap",
        str(tcap),
        "--start",
        "0",
        "--count",
        str(k),
        "--output",
        str(result),
        "--markers",
        str(marker),
    ]


def _run_sample(
    *,
    directory: Path,
    mode: str,
    pair: int,
    order: int,
    implementation: str,
    k: int,
    target_temperature: float | None,
    csv_path: Path,
    tcap: Path,
    worker: Path,
    dataset: Path,
    initializations: Path,
) -> dict[str, Any]:
    short = "tcap" if implementation == TCAP_FULL_IMPLEMENTATION else "eager"
    stem = f"{mode}-pair-{pair:02d}-{order}-{short}"
    result_path = directory / "raw" / f"{stem}.bin"
    marker_path = directory / "raw" / f"{stem}.markers"
    sample_path = directory / "raw" / f"{stem}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if sample_path.is_file():
        value = json.loads(sample_path.read_text(encoding="utf-8"))
        if value.get("accepted"):
            return value
    stable = _wait_stable_start(csv_path, target_c=target_temperature)
    command = _command(
        implementation,
        k=k,
        tcap=tcap,
        worker=worker,
        dataset=dataset,
        initializations=initializations,
        result=result_path,
        marker=marker_path,
    )
    completed, physical = _run_guarded(command, csv_path, timeout=max(300.0, k * 1.2))
    timing = _parse_worker_stdout(implementation, completed.stdout)
    start, end = _marker_window(marker_path)
    _wait_for_bracketing_sample(csv_path, end, timeout_seconds=60.0)
    _, parsed, inspection = inspect_file(csv_path)
    window = integrate_window(parsed, start, end, minimum_samples=MINIMUM_SAMPLES)
    contract, _, cases = validate_full_tcap(tcap)
    results = parse_result_file(result_path)
    receipts, chain = create_receipts(contract=contract, cases=cases, results=results)
    validate_receipts(receipts, k)
    receipt_path = directory / "receipts" / f"{stem}.jsonl"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in receipts),
        encoding="utf-8",
        newline="\n",
    )
    thermal_start = physical["thermal_before"].get("temperature_c")
    accepted = (
        window.status == "PASS"
        and window.sample_count >= MINIMUM_SAMPLES
        and window.coverage >= MINIMUM_COVERAGE
        and physical.get("failure") is None
        and not physical["thermal_before"].get("throttling")
        and not physical["thermal_after"].get("throttling")
    )
    sample = {
        "schema": "casulo-full-worker-energy-sample/1.0",
        "mode": mode,
        "pair_id": pair,
        "order_in_pair": order,
        "implementation": implementation,
        "K": k,
        "accepted": accepted,
        "reason": "accepted" if accepted else window.reason_code,
        "stable_start": stable,
        "start_temperature_c": thermal_start,
        "maximum_temperature_c": physical["maximum_temperature_c"],
        "timing": timing,
        "window": window.to_dict(),
        "joules_per_training": window.energy_joules / k if window.energy_joules is not None else None,
        "seconds_per_training": window.duration_seconds / k,
        "receipts": len(receipts),
        "receipt_chain": chain,
        "receipt_file": str(receipt_path),
        "result_sha256": _sha256_file(result_path),
        "markers_sha256": _sha256_file(marker_path),
        "source_sampling": inspection["sampling"],
    }
    _write_json(sample_path, sample)
    if not accepted:
        rejected = directory / "rejected" / sample_path.name
        rejected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sample_path, rejected)
    return sample


def _warmups(
    *, directory: Path, csv_path: Path, tcap: Path, worker: Path, dataset: Path, initializations: Path
) -> None:
    marker = directory / "warmups-complete.json"
    if marker.is_file():
        return
    rows = []
    (directory / "raw").mkdir(parents=True, exist_ok=True)
    for index in range(3):
        for implementation in (TCAP_FULL_IMPLEMENTATION, EAGER_FULL_IMPLEMENTATION):
            short = "tcap" if implementation == TCAP_FULL_IMPLEMENTATION else "eager"
            result = directory / "raw" / f"warmup-{index + 1}-{short}.bin"
            marks = directory / "raw" / f"warmup-{index + 1}-{short}.markers"
            completed, physical = _run_guarded(
                _command(
                    implementation,
                    k=1,
                    tcap=tcap,
                    worker=worker,
                    dataset=dataset,
                    initializations=initializations,
                    result=result,
                    marker=marks,
                ),
                csv_path,
                timeout=300.0,
            )
            rows.append({"index": index + 1, "implementation": implementation, "timing": _parse_worker_stdout(implementation, completed.stdout), "thermal": physical})
    _write_json(marker, {"schema": "casulo-full-worker-warmups/1.0", "rows": rows})


def _idle(directory: Path, csv_path: Path) -> dict[str, Any]:
    target = directory / "idle.json"
    if target.is_file():
        return json.loads(target.read_text(encoding="utf-8"))
    _wait_stable_start(csv_path)
    start = datetime.now(timezone.utc)
    time.sleep(60.0)
    end = datetime.now(timezone.utc)
    _wait_for_bracketing_sample(csv_path, end)
    _, parsed, _ = inspect_file(csv_path)
    window = integrate_window(parsed, start, end, minimum_samples=MINIMUM_SAMPLES)
    value = {"start_utc": start.isoformat(), "end_utc": end.isoformat(), "window": window.to_dict()}
    _write_json(target, value)
    if window.status != "PASS":
        raise RuntimeError("idle calibration failed: " + json.dumps(value))
    return value


def _schedule(directory: Path) -> dict[str, Any]:
    path = directory / "schedule.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    pairs = []
    for mode in ("work-equivalent", "window-equivalent"):
        for pair in range(1, PAIR_COUNT + 1):
            order = (
                [TCAP_FULL_IMPLEMENTATION, EAGER_FULL_IMPLEMENTATION]
                if pair % 2
                else [EAGER_FULL_IMPLEMENTATION, TCAP_FULL_IMPLEMENTATION]
            )
            pairs.append({"mode": mode, "pair_id": pair, "order": order})
    value = {"schema": "casulo-full-worker-energy-schedule/1.0", "pairs": pairs}
    _write_json(path, value)
    return value


def _run_mode(
    mode: str,
    *,
    directory: Path,
    schedule: dict[str, Any],
    csv_path: Path,
    tcap: Path,
    worker: Path,
    dataset: Path,
    initializations: Path,
) -> list[dict[str, Any]]:
    accepted_pairs = []
    for entry in [item for item in schedule["pairs"] if item["mode"] == mode]:
        pair = entry["pair_id"]
        values = []
        reference_temperature = None
        for order, implementation in enumerate(entry["order"], 1):
            k = COMMON_K if mode == "work-equivalent" else (
                WINDOW_TCAP_K if implementation == TCAP_FULL_IMPLEMENTATION else WINDOW_EAGER_K
            )
            sample = _run_sample(
                directory=directory,
                mode=mode,
                pair=pair,
                order=order,
                implementation=implementation,
                k=k,
                target_temperature=reference_temperature,
                csv_path=csv_path,
                tcap=tcap,
                worker=worker,
                dataset=dataset,
                initializations=initializations,
            )
            if reference_temperature is None:
                reference_temperature = sample["start_temperature_c"]
            values.append(sample)
        starts = [item["start_temperature_c"] for item in values]
        tcap_results = parse_result_file(Path(next(item for item in values if item["implementation"] == TCAP_FULL_IMPLEMENTATION)["receipt_file"]).parents[1] / "raw" / f"{mode}-pair-{pair:02d}-{next(item['order_in_pair'] for item in values if item['implementation'] == TCAP_FULL_IMPLEMENTATION)}-tcap.bin")
        eager_results = parse_result_file(Path(next(item for item in values if item["implementation"] == EAGER_FULL_IMPLEMENTATION)["receipt_file"]).parents[1] / "raw" / f"{mode}-pair-{pair:02d}-{next(item['order_in_pair'] for item in values if item['implementation'] == EAGER_FULL_IMPLEMENTATION)}-eager.bin")
        common = min(len(tcap_results), len(eager_results))
        equivalent = compare_results(tcap_results[:common], eager_results[:common])
        equivalent["directly_compared_cases"] = common
        equivalent["tcap_completed_cases"] = len(tcap_results)
        equivalent["eager_completed_cases"] = len(eager_results)
        if mode == "window-equivalent" and len(tcap_results) != len(eager_results):
            primary_gate = json.loads(
                (directory / "equivalence" / f"work-equivalent-pair-{pair:02d}.json").read_text(encoding="utf-8")
            )
            equivalent["remaining_tcap_cases_gate"] = "PASS_BY_SAME_PAIR_WORK_EQUIVALENT_CAMPAIGN" if primary_gate.get("accepted") else "FAIL"
            if not primary_gate.get("accepted"):
                equivalent["status"] = "FAIL"
        pair_ok = all(item["accepted"] for item in values) and max(starts) - min(starts) <= 1.0 and equivalent["status"] == "PASS"
        pair_record = {"mode": mode, "pair_id": pair, "accepted": pair_ok, "start_temperature_difference_c": max(starts) - min(starts), "equivalence": equivalent, "samples": values}
        _write_json(directory / "equivalence" / f"{mode}-pair-{pair:02d}.json", pair_record)
        if not pair_ok:
            raise RuntimeError("definitive pair rejected fail-closed: " + json.dumps(pair_record))
        accepted_pairs.append(pair_record)
    return accepted_pairs


def _analyze_mode(mode: str, pairs: list[dict[str, Any]], idle_watts: float) -> dict[str, Any]:
    rows = []
    t_values, e_values = [], []
    for pair in pairs:
        by_name = {item["implementation"]: item for item in pair["samples"]}
        tcap, eager = by_name[TCAP_FULL_IMPLEMENTATION], by_name[EAGER_FULL_IMPLEMENTATION]
        tj, ej = tcap["joules_per_training"], eager["joules_per_training"]
        t_values.append(tj)
        e_values.append(ej)
        rows.append({
            "pair_id": pair["pair_id"],
            "tcap_joules_per_training": tj,
            "eager_joules_per_training": ej,
            "ratio_tcap_over_eager": tj / ej,
            "tcap_seconds_per_training": tcap["seconds_per_training"],
            "eager_seconds_per_training": eager["seconds_per_training"],
            "tcap_watts": tcap["window"]["average_watts"],
            "eager_watts": eager["window"]["average_watts"],
            "tcap_trainings_per_joule": 1 / tj,
            "eager_trainings_per_joule": 1 / ej,
            "start_temperature_difference_c": pair["start_temperature_difference_c"],
            "tcap_maximum_temperature_c": tcap["maximum_temperature_c"],
            "eager_maximum_temperature_c": eager["maximum_temperature_c"],
        })
    ratios = tuple(item["ratio_tcap_over_eager"] for item in rows)
    low, high = paired_bootstrap_ci(ratios, seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES)
    median = statistics.median(ratios)
    return {
        "mode": mode,
        "valid_pairs": len(rows),
        "pairs": rows,
        "median_joules_per_training": {TCAP_FULL_IMPLEMENTATION: statistics.median(t_values), EAGER_FULL_IMPLEMENTATION: statistics.median(e_values)},
        "median_ratio_tcap_over_eager": median,
        "paired_bootstrap_ci95": {"lower": low, "upper": high, "seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES},
        "exact_sign_test": exact_sign_test(t_values, e_values),
        "idle_average_watts": idle_watts,
        "advantage_gate": len(rows) == PAIR_COUNT and median < 1 and high < 1,
    }


def _extract_segment(csv_path: Path, output: Path, start: datetime, end: datetime) -> None:
    _, parsed, _ = inspect_file(csv_path)
    rows = [item for item in parsed.rows if start <= item.timestamp_utc <= end]
    if not rows:
        raise RuntimeError("no HWiNFO rows overlap the campaign")
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        last_session = None
        for row in rows:
            if row.session_id != last_session:
                writer.writerow(parsed.headers[row.session_id])
                last_session = row.session_id
            writer.writerow(row.values)


def _seal(directory: Path, terminal: str) -> None:
    files = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.name not in {"MANIFEST.json", "SHA256SUMS"}):
        files.append({"path": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256_file(path)})
    _write_json(directory / "MANIFEST.json", {"schema": "casulo-full-worker-energy-manifest/1.0", "campaign_id": directory.name, "terminal_state": terminal, "files": files})
    lines = [f"{item['sha256']}  {item['path']}" for item in files]
    lines.append(f"{_sha256_file(directory / 'MANIFEST.json')}  MANIFEST.json")
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def _finalize_blocked(directory: Path, csv_path: Path) -> dict[str, Any]:
    terminal = "BLOCKED_THERMAL_OR_SENSOR"
    calibration_files = sorted((directory / "raw").glob("calibration-*.json"))
    calibration = [json.loads(path.read_text(encoding="utf-8")) for path in calibration_files]
    _write_json(directory / "calibration.json", {"samples": calibration, "complete": False})
    blocker = {
        "schema": "casulo-full-worker-energy-blocker/1.0",
        "terminal_state": terminal,
        "reason": "instantaneous_thermal_throttling_detected_during_calibration_cooldown",
        "trigger_observation": {
            "hwinfo_timestamp_utc": "2026-08-08T14:19:54.187000+00:00",
            "temperature_c": 68.0,
            "throttling": True,
            "ac_connected": True,
            "battery_percent": 100.0,
        },
        "observed_guard": _live_guard(csv_path, during_load=False),
        "definitive_pairs_started": 0,
        "definitive_pairs_valid": 0,
        "tcap_calibration_preserved": bool(calibration),
        "tcap_calibration_is_not_comparative_evidence": True,
        "next_physical_action": "allow a full cooldown and investigate the instantaneous HWiNFO throttling flag before starting a new campaign ID",
    }
    _write_json(directory / "campaign_blocker.json", blocker)
    analysis = {
        "schema": "casulo-full-worker-energy-analysis/1.0",
        "terminal_state": terminal,
        "full_worker_validation": "PASS",
        "full_worker_validation_directory": str(DEFAULT_FULL.resolve()),
        "valid_pairs": 0,
        "comparison_joules_per_training": None,
        "energy_advantage": "NOT_EVALUATED",
        "calibration": calibration,
        "blocker": blocker,
        "limitations": {
            "TOTAL_SYSTEM_WALL": "BLOCKED_PHYSICAL_INSTRUMENT",
            "CASULO_NATIVE_ENERGY": "BLOCKED_PHYSICAL_INSTRUMENT",
            "Inductor": "NOT_TESTED",
            "GPU_TPU_DATACENTER": "NOT_MEASURED",
        },
    }
    _write_json(directory / "analysis.json", analysis)
    protocol_path = directory / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["source_csv_final_sha256"] = _sha256_file(csv_path)
    _write_json(protocol_path, protocol)
    markers = []
    for path in sorted((directory / "raw").glob("*.markers")):
        try:
            start, end = _marker_window(path)
        except (OSError, ValueError):
            continue
        markers.append({"file": path.name, "start_utc": start.isoformat(), "end_utc": end.isoformat(), "sha256": _sha256_file(path)})
    (directory / "markers.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in markers),
        encoding="utf-8",
        newline="\n",
    )
    idle = json.loads((directory / "idle.json").read_text(encoding="utf-8"))
    _extract_segment(csv_path, directory / "source_segment.csv", datetime.fromisoformat(idle["start_utc"]), datetime.now(timezone.utc))
    report = [
        "# Energia do worker FloodSurrogate completo",
        "",
        f"**Estado científico:** `{terminal}`",
        "",
        "O worker científico completo passou seus gates de trabalho, receipts, linearidade, relógios e equivalência. A campanha energética definitiva não começou.",
        "",
        "## Bloqueio físico",
        "",
        "O HWiNFO informou thermal throttling instantâneo durante o cooldown da calibração. A regra congelada exige zero throttling, portanto a coleta parou antes do primeiro par.",
        "",
        "A janela TCAP de calibração (620 treinamentos) foi preservada, mas não é comparação energética e não autoriza alegação de vantagem.",
        "",
        "## Limites",
        "",
        "- Pares definitivos: 0/21",
        "- Joules comparativos: indisponíveis",
        "- `TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`",
        "- `CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`",
        "",
    ]
    (directory / "report.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    _seal(directory, terminal)
    return analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-worker", type=Path, default=DEFAULT_FULL)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--calibration-only", action="store_true")
    parser.add_argument("--finalize-blocked", action="store_true")
    args = parser.parse_args()
    full = args.full_worker.resolve(strict=True)
    csv_path = args.csv.resolve(strict=True)
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.finalize_blocked:
        value = _finalize_blocked(directory, csv_path)
        print(json.dumps(value, indent=2))
        return 0
    initial_hash = _sha256_file(csv_path)
    tcap = full / "artifact/FloodSurrogate.full.tcap"
    contract, _, _ = validate_full_tcap(tcap)
    worker_build = build_full_native_worker(tcap, directory / "worker")
    worker = Path(worker_build["executable"])
    dataset = full / "artifact/FloodSurrogate.dataset.bin"
    initializations = full / "artifact/FloodSurrogate.initializations.bin"
    _, _, inspection = inspect_file(csv_path)
    sensor = inspection["selected_energy_sensor"]
    if not sensor or sensor["literal_name"].replace("�", "ê") != "Potência total da CPU [W]" or sensor["unit"] != "w":
        raise RuntimeError("required physical HWiNFO CPU package power sensor is unavailable")
    protocol = {
        "schema": "casulo-full-worker-energy-protocol/1.0",
        "campaign_id": directory.name,
        "source_scope": "HWiNFO-reported CPU package energy on bare-metal Windows",
        "sensor": sensor,
        "sampling": inspection["sampling"],
        "pair_count": PAIR_COUNT,
        "work_equivalent_K": COMMON_K,
        "window_equivalent_K": {TCAP_FULL_IMPLEMENTATION: WINDOW_TCAP_K, EAGER_FULL_IMPLEMENTATION: WINDOW_EAGER_K},
        "minimum_samples": MINIMUM_SAMPLES,
        "minimum_coverage": MINIMUM_COVERAGE,
        "thermal_start_target_c": START_TARGET_C,
        "thermal_pair_tolerance_c": 1.0,
        "thermal_hard_limit_c": HARD_LIMIT_C,
        "throttling_allowed": False,
        "threads": 1,
        "affinity": [4],
        "contract": contract.to_dict(),
        "source_csv": str(csv_path),
        "source_csv_initial_sha256": initial_hash,
        "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
        "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
    }
    _write_json(directory / "protocol.json", protocol)
    _write_json(directory / "worker_build.json", worker_build)
    campaign_start = datetime.now(timezone.utc)
    idle = _idle(directory, csv_path)
    _warmups(directory=directory, csv_path=csv_path, tcap=tcap, worker=worker, dataset=dataset, initializations=initializations)
    schedule = _schedule(directory)
    # Calibration validates the short 20-second windows; common-K A is frozen
    # from the already-passed linear model and intentionally not run as a hidden
    # pilot that could bias the definitive schedule.
    calibration = []
    for implementation, k in ((TCAP_FULL_IMPLEMENTATION, WINDOW_TCAP_K), (EAGER_FULL_IMPLEMENTATION, WINDOW_EAGER_K)):
        calibration.append(_run_sample(directory=directory, mode="calibration", pair=0, order=len(calibration)+1, implementation=implementation, k=k, target_temperature=None if not calibration else calibration[0]["start_temperature_c"], csv_path=csv_path, tcap=tcap, worker=worker, dataset=dataset, initializations=initializations))
    _write_json(directory / "calibration.json", {"samples": calibration})
    if not all(item["accepted"] for item in calibration):
        raise RuntimeError("full-worker energy calibration failed")
    if args.calibration_only:
        print(json.dumps({"status": "CALIBRATION_PASS", "directory": str(directory), "samples": calibration}, indent=2))
        return 0
    modes = {}
    for mode in ("work-equivalent", "window-equivalent"):
        pairs = _run_mode(mode, directory=directory, schedule=schedule, csv_path=csv_path, tcap=tcap, worker=worker, dataset=dataset, initializations=initializations)
        modes[mode] = _analyze_mode(mode, pairs, idle["window"]["average_watts"])
    primary = modes["work-equivalent"]
    if primary["advantage_gate"]:
        terminal = "PASS_FULL_WORKER_AND_ENERGY"
    elif primary["paired_bootstrap_ci95"]["lower"] <= 1 <= primary["paired_bootstrap_ci95"]["upper"]:
        terminal = "PASS_FULL_WORKER_ENERGY_INCONCLUSIVE"
    else:
        terminal = "PASS_FULL_WORKER_NO_ENERGY_ADVANTAGE"
    analysis = {"schema": "casulo-full-worker-energy-analysis/1.0", "terminal_state": terminal, "modes": modes, "limitations": {"TOTAL_SYSTEM_WALL": "BLOCKED_PHYSICAL_INSTRUMENT", "CASULO_NATIVE_ENERGY": "BLOCKED_PHYSICAL_INSTRUMENT", "Inductor": "NOT_TESTED", "GPU_TPU_DATACENTER": "NOT_MEASURED"}}
    _write_json(directory / "analysis.json", analysis)
    final_hash = _sha256_file(csv_path)
    protocol["source_csv_final_sha256"] = final_hash
    _write_json(directory / "protocol.json", protocol)
    campaign_end = datetime.now(timezone.utc)
    _extract_segment(csv_path, directory / "source_segment.csv", campaign_start, campaign_end)
    report = ["# Energia do worker FloodSurrogate completo", "", f"**Estado científico:** `{terminal}`", "", "A medição abrange exclusivamente energia do pacote CPU reportada pelo HWiNFO no Windows físico.", "", "## Campanha A — trabalho equivalente", "", f"- Pares: {primary['valid_pairs']}/21", f"- TCAP: {primary['median_joules_per_training'][TCAP_FULL_IMPLEMENTATION]:.9f} J/treinamento", f"- Eager: {primary['median_joules_per_training'][EAGER_FULL_IMPLEMENTATION]:.9f} J/treinamento", f"- Razão TCAP/Eager: {primary['median_ratio_tcap_over_eager']:.9f}", f"- IC95%: [{primary['paired_bootstrap_ci95']['lower']:.9f}, {primary['paired_bootstrap_ci95']['upper']:.9f}]", "", "## Limites", "", "- `TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`", "- `CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`", "- Sem alegação sobre Inductor, GPU/TPU, datacenter ou outros hosts.", ""]
    (directory / "report.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    _seal(directory, terminal)
    print(json.dumps({"status": terminal, "directory": str(directory), "primary": primary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
