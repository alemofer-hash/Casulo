from __future__ import annotations

import hashlib
import csv
import io
import json
import math
import os
import queue
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .analysis import exact_sign_test, paired_bootstrap_ci
from .hwinfo import (
    HWiNFOError,
    _is_header,
    _parse_timestamp,
    inspect_file,
    integrate_window,
    read_shared_snapshot,
)
from .hwinfo_workers import (
    EAGER_IMPLEMENTATION,
    TCAP_IMPLEMENTATION,
    build_native_worker,
    validate_scientific_training_unit,
)
from .schemas import canonical_bytes, read_json, sha256_bytes, sha256_file, write_json


CAMPAIGN_SCHEMA = "casulo-hwinfo-energy-campaign/1.0"
SAMPLE_SCHEMA = "casulo-hwinfo-energy-sample/1.0"
ANALYSIS_SCHEMA = "casulo-hwinfo-energy-analysis/1.0"
DEFAULT_CAMPAIGN_ID = "2026-08-07-g5-hwinfo-tcap-vs-eager"
WORKLOAD = "flood-surrogate-canary-400"
SOURCE_DOMAIN = "HWINFO_REPORTED_CPU_PACKAGE_ENERGY_WINDOWS"
THREADS = 1
AFFINITY = (4,)
PAIR_COUNT = 21
BOOTSTRAP_SEED = 20260807
BOOTSTRAP_RESAMPLES = 20_000
SEGMENT_TARGET_SECONDS = 5.0
MAXIMUM_CONTINUOUS_SECONDS = 20.0
RESUME_BELOW_C = 55.0
WARNING_C = 75.0
SOFT_STOP_C = 80.0
HARD_STOP_C = 85.0
PHYSICAL_GUARD_POLL_SECONDS = 0.25


@dataclass(slots=True)
class HWiNFOLiveTail:
    """Bounded latest-row reader for the physical watchdog.

    Scientific integration continues to use the immutable full snapshot.  The
    watchdog only needs the newest row and must not reparse a growing multi-MB
    campaign file several times per second.
    """

    path: Path
    tail_bytes: int = 256 * 1024
    encoding: str = "utf-8-sig"
    delimiter: str = ","
    header: tuple[str, ...] = ()
    latest_values: tuple[str, ...] = ()
    latest_timestamp_utc: datetime | None = None
    last_size: int = 0

    def initialize(self) -> None:
        snapshot, parsed, _ = inspect_file(self.path)
        if not parsed.rows or not parsed.headers:
            raise HWiNFOError("HWiNFO live tail has no complete row")
        latest = parsed.rows[-1]
        self.encoding = parsed.encoding
        self.delimiter = parsed.delimiter
        self.header = parsed.headers[min(latest.session_id, len(parsed.headers) - 1)]
        self.latest_values = latest.values
        self.latest_timestamp_utc = latest.timestamp_utc
        self.last_size = snapshot.file_size_at_open

    def read_latest(self) -> tuple[tuple[str, ...], tuple[str, ...], datetime, int]:
        source = self.path
        stat = source.stat()
        if not self.header or stat.st_size < self.last_size:
            self.initialize()
            stat = source.stat()
        start = max(0, stat.st_size - self.tail_bytes)
        with source.open("rb") as handle:
            handle.seek(start)
            data = handle.read(stat.st_size - start)
        if start:
            newline = data.find(b"\n")
            data = data[newline + 1 :] if newline >= 0 else b""
        if data and not data.endswith((b"\n", b"\r")):
            newline = max(data.rfind(b"\n"), data.rfind(b"\r"))
            data = data[: newline + 1] if newline >= 0 else b""
        codec = self.encoding if start == 0 else self.encoding.removesuffix("-sig")
        text = data.decode(codec, errors="strict")
        tz = datetime.now().astimezone().tzinfo
        if tz is None:
            raise HWiNFOError("local timezone is unavailable")
        reader = csv.reader(io.StringIO(text), delimiter=self.delimiter)
        header = self.header
        latest_values = self.latest_values
        latest_timestamp = self.latest_timestamp_utc
        for row in reader:
            if not row or not any(item.strip() for item in row):
                continue
            if _is_header(row):
                header = tuple(row)
                continue
            if not header or len(row) < len(header):
                continue
            try:
                local = _parse_timestamp(row[0], row[1], tz)
            except (ValueError, IndexError):
                continue
            latest_values = tuple(row[: len(header)])
            latest_timestamp = local.astimezone(timezone.utc)
        if latest_timestamp is None or not latest_values:
            raise HWiNFOError("HWiNFO live tail has no valid latest row")
        self.header = header
        self.latest_values = latest_values
        self.latest_timestamp_utc = latest_timestamp
        self.last_size = stat.st_size
        return header, latest_values, latest_timestamp, stat.st_size


@dataclass(slots=True)
class HWiNFOIncrementalWatcher:
    """Read only bytes appended after initialization and retain one partial line."""

    path: Path
    maximum_chunk_bytes: int = 1024 * 1024
    encoding: str = "utf-8-sig"
    delimiter: str = ","
    header: tuple[str, ...] = ()
    latest_values: tuple[str, ...] = ()
    latest_timestamp_utc: datetime | None = None
    offset: int = 0
    partial: bytes = b""
    bytes_read_total: int = 0
    maximum_observed_chunk_bytes: int = 0

    def initialize(self) -> None:
        snapshot, parsed, _ = inspect_file(self.path)
        if not parsed.rows or not parsed.headers:
            raise HWiNFOError("HWiNFO incremental watcher has no complete row")
        latest = parsed.rows[-1]
        self.encoding = parsed.encoding
        self.delimiter = parsed.delimiter
        self.header = parsed.headers[min(latest.session_id, len(parsed.headers) - 1)]
        self.latest_values = latest.values
        self.latest_timestamp_utc = latest.timestamp_utc
        self.offset = snapshot.file_size_at_open
        self.partial = b""

    def read_latest(self) -> tuple[tuple[str, ...], tuple[str, ...], datetime, int]:
        stat = self.path.stat()
        if not self.header or stat.st_size < self.offset:
            self.initialize()
            stat = self.path.stat()
        available = stat.st_size - self.offset
        if available > self.maximum_chunk_bytes:
            raise HWiNFOError("HWiNFO incremental watcher fell behind its bounded chunk budget")
        data = b""
        if available:
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read(available)
            self.offset += len(data)
            self.bytes_read_total += len(data)
            self.maximum_observed_chunk_bytes = max(self.maximum_observed_chunk_bytes, len(data))
        combined = self.partial + data
        split = combined.splitlines(keepends=True)
        complete: list[bytes] = []
        self.partial = b""
        for index, line in enumerate(split):
            if line.endswith((b"\n", b"\r")):
                complete.append(line)
            elif index == len(split) - 1:
                self.partial = line
            else:
                complete.append(line)
        if len(self.partial) > self.maximum_chunk_bytes:
            raise HWiNFOError("HWiNFO partial line exceeds the bounded memory budget")
        if complete:
            codec = self.encoding.removesuffix("-sig")
            text = b"".join(complete).decode(codec, errors="strict")
            timezone_local = datetime.now().astimezone().tzinfo
            if timezone_local is None:
                raise HWiNFOError("local timezone is unavailable")
            header = self.header
            values = self.latest_values
            timestamp = self.latest_timestamp_utc
            for row in csv.reader(io.StringIO(text), delimiter=self.delimiter):
                if not row or not any(item.strip() for item in row):
                    continue
                if _is_header(row):
                    header = tuple(row)
                    continue
                if len(row) < len(header):
                    continue
                try:
                    local = _parse_timestamp(row[0], row[1], timezone_local)
                except (ValueError, IndexError):
                    continue
                values = tuple(row[: len(header)])
                timestamp = local.astimezone(timezone.utc)
            self.header, self.latest_values, self.latest_timestamp_utc = header, values, timestamp
        if self.latest_timestamp_utc is None:
            raise HWiNFOError("HWiNFO incremental watcher has no timestamp")
        return self.header, self.latest_values, self.latest_timestamp_utc, stat.st_size

    def budget(self) -> dict[str, Any]:
        return {
            "reader": "append-only-incremental-v1",
            "offset": self.offset,
            "bytes_read_total": self.bytes_read_total,
            "maximum_observed_chunk_bytes": self.maximum_observed_chunk_bytes,
            "partial_bytes": len(self.partial),
            "maximum_chunk_bytes": self.maximum_chunk_bytes,
        }


_LIVE_TAILS: dict[str, HWiNFOLiveTail] = {}
_LIVE_TAILS_LOCK = threading.Lock()
@dataclass(slots=True)
class PersistentWorker:
    implementation: str
    command: list[str]
    process: subprocess.Popen[str] | None = None
    ready: dict[str, Any] | None = None

    def start(self) -> dict[str, Any]:
        if self.process is not None:
            return dict(self.ready or {})
        environment = os.environ.copy()
        environment["OMP_NUM_THREADS"] = str(THREADS)
        environment["MKL_NUM_THREADS"] = str(THREADS)
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=environment,
        )
        line = self.process.stdout.readline() if self.process.stdout else ""
        if not line:
            error = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"{self.implementation} worker failed before READY: {error}")
        ready = json.loads(line)
        if ready.get("event") != "READY" or ready.get("implementation") != self.implementation:
            raise RuntimeError(f"invalid worker READY: {ready}")
        self.ready = ready
        self._set_affinity()
        return dict(ready)

    @property
    def pid(self) -> int:
        if self.process is None:
            raise RuntimeError("worker not started")
        return self.process.pid

    def run(
        self,
        count: int,
        *,
        timeout_seconds: float,
        guard: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("worker not started")
        output: queue.Queue[tuple[str, str]] = queue.Queue()

        def read_one() -> None:
            try:
                output.put(("line", self.process.stdout.readline()))
            except Exception as exc:  # pragma: no cover - OS pipe failure
                output.put(("error", str(exc)))

        self.process.stdin.write(f"RUN {count}\n")
        self.process.stdin.flush()
        thread = threading.Thread(target=read_one, daemon=True)
        thread.start()
        observations: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                kind, payload = output.get(timeout=PHYSICAL_GUARD_POLL_SECONDS)
            except queue.Empty:
                state = guard()
                observations.append(state)
                if not state["safe_during_load"]:
                    self.process.terminate()
                    raise RuntimeError(
                        "physical_guard:"
                        + json.dumps(
                            state,
                            ensure_ascii=False,
                            allow_nan=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                continue
            if kind == "error":
                raise RuntimeError(payload)
            if not payload:
                error = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(f"worker exited during RUN: {error}")
            result = json.loads(payload)
            if result.get("event") != "RESULT" or result.get("status") != "PASS":
                raise RuntimeError(f"worker result invalid: {result}")
            return result, observations
        self.process.terminate()
        raise TimeoutError(f"{self.implementation} segment exceeded timeout")

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.poll() is None and self.process.stdin is not None:
                self.process.stdin.write("STOP\n")
                self.process.stdin.flush()
                self.process.wait(timeout=5)
        except Exception:
            self.process.terminate()
        finally:
            self.process = None

    def _set_affinity(self) -> None:
        try:
            import psutil

            psutil.Process(self.pid).cpu_affinity(list(AFFINITY))
        except Exception as exc:
            raise RuntimeError(f"failed to establish identical CPU affinity: {exc}") from exc


def inspect_hwinfo(csv_path: Path) -> dict[str, Any]:
    snapshot, _, report = inspect_file(csv_path)
    return {
        "status": "PASS" if report["selected_energy_sensor"] else "BLOCKED_HWINFO_REQUIRED_SENSOR",
        "scientific_scope": "HWiNFO-reported CPU package energy on bare-metal Windows",
        "source_csv": str(Path(csv_path).resolve()),
        "snapshot": snapshot.metadata(),
        "inspection": report,
    }


def initialize_campaign(
    root: Path,
    csv_path: Path,
    tcap_path: Path,
    campaign_id: str = DEFAULT_CAMPAIGN_ID,
    *,
    _allow_bounded_canary_for_nonperformance_test: bool = False,
) -> Path:
    if not _allow_bounded_canary_for_nonperformance_test:
        validate_scientific_training_unit(tcap_path)
    root = Path(root)
    campaign_id = allocate_campaign_id(root, campaign_id)
    directory = root / campaign_id
    if directory.exists() and not (directory / "protocol.json").exists():
        raise RuntimeError(f"existing incomplete directory requires explicit recovery: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("raw", "rejected", "equivalence", "workers"):
        (directory / name).mkdir(exist_ok=True)
    inspection = inspect_hwinfo(csv_path)
    if inspection["status"] != "PASS":
        write_json(directory / "hwinfo_source.json", inspection)
        raise HWiNFOError("BLOCKED_HWINFO_REQUIRED_SENSOR")
    if not (directory / "protocol.json").exists():
        source = inspection["inspection"]
        snapshot = inspection["snapshot"]
        initial_capture = {
            "captured_before_workload": True,
            "captured_at_utc": _utc(),
            "byte_offset": snapshot["bytes_read"],
            "sha256_snapshot": snapshot["sha256"],
            "last_timestamp_utc": source["last_timestamp_utc"],
            "source_history": _infer_source_history(Path(csv_path), source),
            "note": "bounded shared-read snapshot captured before workload in this campaign",
        }
        median_interval = source["sampling"]["median_seconds"]
        required = max(120.0, 100.0 * float(median_interval))
        schedule = _schedule()
        protocol = {
            "schema": CAMPAIGN_SCHEMA,
            "campaign_id": campaign_id,
            "created_at_utc": _utc(),
            "claim_scope": "HWiNFO-reported CPU package energy on bare-metal Windows",
            "candidate": TCAP_IMPLEMENTATION,
            "baseline": EAGER_IMPLEMENTATION,
            "workload": WORKLOAD,
            "epochs": 400,
            "precision": "float64",
            "threads": THREADS,
            "affinity": list(AFFINITY),
            "pairs": PAIR_COUNT,
            "warmups_per_implementation": 3,
            "schedule": "deterministic alternating AB/BA frozen before results",
            "minimum_measured_seconds_per_sample": required,
            "minimum_hwinfo_samples_per_sample": 60,
            "segment_target_seconds": SEGMENT_TARGET_SECONDS,
            "maximum_continuous_seconds": MAXIMUM_CONTINUOUS_SECONDS,
            "thermal_policy": {
                "resume_below_c": RESUME_BELOW_C,
                "warning_c": WARNING_C,
                "soft_stop_c": SOFT_STOP_C,
                "hard_stop_c": HARD_STOP_C,
                "persistent_throttling_allowed": False,
                "maximum_median_temperature_asymmetry_c": 3.0,
            },
            "idle_load_response_preregistered": {
                "load_median_watts_must_exceed": "idle_median + max(2 W, 25% of idle_median)",
                "registered_before_calibration_observation": True,
            },
            "bootstrap": {"seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES},
            "outlier_policy": "no post-observation outlier removal",
            "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
            "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
        }
        write_json(directory / "protocol.json", protocol)
        write_json(directory / "schedule.json", schedule)
        write_json(directory / "hwinfo_source.json", inspection)
        (directory / "source_csv_initial.sha256").write_text(
            f"{initial_capture['sha256_snapshot']}  {Path(csv_path).name} bytes=0:{initial_capture['byte_offset']}\n",
            encoding="ascii",
            newline="\n",
        )
        write_json(directory / "h0_initial_capture.json", {**initial_capture, "source_csv": str(Path(csv_path).resolve())})
        write_json(directory / "input_hashes.json", {
            "tcap_sha256": sha256_file(tcap_path),
            "dataset_sha256": _dataset_sha(tcap_path),
            "configuration_sha256": sha256_bytes(canonical_bytes(protocol)),
        })
    return directory


def allocate_campaign_id(root: Path, requested: str) -> str:
    """Reuse only an unsealed transaction; never overwrite sealed evidence."""

    base = Path(root) / requested
    if not base.exists() or not (base / "MANIFEST.json").exists():
        return requested
    index = 2
    while True:
        candidate = f"{requested}-{index:02d}"
        if not (Path(root) / candidate).exists():
            return candidate
        index += 1


def prepare_workers(directory: Path, tcap_path: Path) -> tuple[PersistentWorker, PersistentWorker, dict[str, Any]]:
    build_path = directory / "workers"
    build = build_native_worker(tcap_path, build_path)
    write_json(directory / "worker_build.json", build)
    native = PersistentWorker(TCAP_IMPLEMENTATION, [build["executable"]])
    eager = PersistentWorker(EAGER_IMPLEMENTATION, [
        sys.executable, "-m", "casulo.livelab.energy_v1.hwinfo_workers", "--eager-worker",
        "--tcap", str(Path(tcap_path).resolve()), "--threads", str(THREADS),
    ])
    starts = {TCAP_IMPLEMENTATION: native.start(), EAGER_IMPLEMENTATION: eager.start()}
    write_json(directory / "worker_environment.json", starts)
    return native, eager, build


def run_equivalence(directory: Path, workers: tuple[PersistentWorker, PersistentWorker], csv_path: Path, tcap_path: Path) -> dict[str, Any]:
    results = {}
    for worker in workers:
        result, _ = worker.run(1, timeout_seconds=30, guard=lambda: _live_guard(csv_path, during_load=True))
        result = _complete_native_result(result, tcap_path)
        results[worker.implementation] = result
        write_json(directory / "equivalence" / (worker.implementation.replace("/", "_") + ".json"), result)
    candidate = results[TCAP_IMPLEMENTATION]
    baseline = results[EAGER_IMPLEMENTATION]
    if candidate["dataset_sha256"] != baseline["dataset_sha256"]:
        raise RuntimeError("equivalence dataset hashes differ")
    differences = {
        "initial_loss": abs(candidate["loss"]["initial"] - baseline["loss"]["initial"]),
        "final_loss": abs(candidate["loss"]["final"] - baseline["loss"]["final"]),
        "parameters_max_abs": max(abs(a - b) for a, b in zip(candidate["parameters"], baseline["parameters"], strict=True)),
        "predictions_max_abs": max(abs(a - b) for a, b in zip(candidate["predictions"], baseline["predictions"], strict=True)),
    }
    passed = all(value <= 1e-9 for value in differences.values())
    gate = {
        "status": "PASS" if passed else "FAIL",
        "epochs": 400,
        "same_dataset": True,
        "same_initial_parameters": True,
        "same_precision": True,
        "same_threads": True,
        "tolerance": 1e-9,
        "differences": differences,
        "implementations": results,
    }
    write_json(directory / "equivalence" / "gate.json", gate)
    if not passed:
        raise RuntimeError("mathematical equivalence gate failed")
    return gate


def calibrate_campaign(
    directory: Path,
    workers: tuple[PersistentWorker, PersistentWorker],
    csv_path: Path,
    tcap_path: Path,
) -> dict[str, Any]:
    calibration_path = directory / "calibration.json"
    if calibration_path.exists():
        return read_json(calibration_path)
    protocol = read_json(directory / "protocol.json")
    marker = directory / "benchmark_markers.jsonl"
    idle = _idle_window(csv_path, marker, seconds=120.0)
    probes = {}
    for worker in workers:
        probe_k = 10_000 if worker.implementation == TCAP_IMPLEMENTATION else 10
        _wait_safe_start(csv_path)
        result, _ = worker.run(probe_k, timeout_seconds=30, guard=lambda: _live_guard(csv_path, during_load=True))
        result = _complete_native_result(result, tcap_path)
        probes[worker.implementation] = result
    # Controlled load is segmented and excluded from the definitive samples.
    load_segments = []
    accumulated = 0.0
    eager = next(item for item in workers if item.implementation == EAGER_IMPLEMENTATION)
    seconds_per = probes[EAGER_IMPLEMENTATION]["seconds_per_training"]
    segment_k = max(1, math.floor(SEGMENT_TARGET_SECONDS / seconds_per))
    while accumulated < 120.0:
        segment = _run_segment(directory, csv_path, eager, segment_k, "calibration-load", f"load-{len(load_segments)+1:03d}", tcap_path)
        load_segments.append(segment)
        accumulated += segment["elapsed_seconds"]
    load_energy = sum(item["energy_joules"] for item in load_segments)
    load_duration = sum(item["elapsed_seconds"] for item in load_segments)
    load_watts = load_energy / load_duration
    threshold = idle["average_watts"] + max(2.0, 0.25 * idle["average_watts"])
    response_pass = load_watts >= threshold
    required = float(protocol["minimum_measured_seconds_per_sample"])
    frozen = {}
    for implementation, result in probes.items():
        # 10% guard band makes the frozen K robust to ordinary runtime variance.
        k = math.ceil(required * 1.10 / result["seconds_per_training"])
        per_segment = max(1, math.floor(SEGMENT_TARGET_SECONDS / result["seconds_per_training"]))
        frozen[implementation] = {
            "K": k,
            "segment_K": per_segment,
            "predicted_seconds": k * result["seconds_per_training"],
            "probe_seconds_per_training": result["seconds_per_training"],
        }
    calibration = {
        "status": "PASS" if response_pass else "FAIL_SENSOR_RESPONSE",
        "idle": idle,
        "controlled_load": {
            "segments": len(load_segments),
            "duration_seconds": load_duration,
            "energy_joules": load_energy,
            "average_watts": load_watts,
            "response_threshold_watts": threshold,
            "response_pass": response_pass,
        },
        "probes": probes,
        "frozen_K": frozen,
        "frozen_before_definitive_campaign": True,
    }
    write_json(calibration_path, calibration)
    if not response_pass:
        raise RuntimeError("HWiNFO package power did not respond coherently to controlled load")
    return calibration


def execute_pairs(
    directory: Path,
    workers: tuple[PersistentWorker, PersistentWorker],
    csv_path: Path,
    tcap_path: Path,
) -> dict[str, Any]:
    calibration = read_json(directory / "calibration.json")
    equivalence = read_json(directory / "equivalence" / "gate.json")
    if calibration["status"] != "PASS" or equivalence["status"] != "PASS":
        raise RuntimeError("calibration and equivalence must pass before campaign")
    by_name = {item.implementation: item for item in workers}
    completed = _completed_pairs(directory)
    if not (directory / "warmups.json").exists():
        warmups = []
        for index in range(3):
            for implementation in (TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION):
                _append_jsonl(directory / "benchmark_markers.jsonl", _marker("warmup_start", "warmup", f"{index + 1}-{_slug(implementation)}", by_name[implementation]))
                result, _ = by_name[implementation].run(1, timeout_seconds=30, guard=lambda: _live_guard(csv_path, during_load=True))
                _append_jsonl(directory / "benchmark_markers.jsonl", _marker("warmup_end", "warmup", f"{index + 1}-{_slug(implementation)}", by_name[implementation]))
                warmups.append({"index": index + 1, "implementation": implementation, "result": _complete_native_result(result, tcap_path)})
        write_json(directory / "warmups.json", {"outside_measurement": True, "warmups": warmups})
    for item in _schedule():
        pair_id = item["pair_id"]
        if pair_id in completed:
            continue
        pair_results = []
        for order, implementation in enumerate(item["order"], 1):
            frozen = calibration["frozen_K"][implementation]
            sample = _run_sample(
                directory, csv_path, by_name[implementation], int(frozen["K"]),
                int(frozen["segment_K"]), "session-01", pair_id, order, tcap_path,
            )
            pair_results.append(sample)
            destination = directory / ("raw" if sample["accepted"] else "rejected") / f"{pair_id}-{order}-{_slug(implementation)}.json"
            write_json(destination, sample)
            if not sample["accepted"]:
                break
        if len(pair_results) == 2 and all(value["accepted"] for value in pair_results):
            completed.add(pair_id)
        else:
            raise RuntimeError(f"pair {pair_id} rejected; physical campaign stopped fail-closed")
    state = {"status": "COLLECTION_COMPLETE", "valid_pairs": len(completed), "expected_pairs": PAIR_COUNT, "observed_at_utc": _utc()}
    write_json(directory / "collection_state.json", state)
    return state


def analyze_hwinfo_campaign(directory: Path) -> dict[str, Any]:
    samples = [read_json(path) for path in sorted((directory / "raw").glob("pair-*.json"))]
    pairs = []
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault(sample["pair_id"], {})[sample["implementation"]] = sample
    for pair_id, values in sorted(grouped.items()):
        if set(values) != {TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION}:
            continue
        candidate, baseline = values[TCAP_IMPLEMENTATION], values[EAGER_IMPLEMENTATION]
        t_j = candidate["joules_per_training"]
        e_j = baseline["joules_per_training"]
        pairs.append({
            "pair_id": pair_id,
            "tcap_joules_per_training": t_j,
            "eager_joules_per_training": e_j,
            "ratio_tcap_over_eager": t_j / e_j,
            "tcap_seconds_per_training": candidate["seconds_per_training"],
            "eager_seconds_per_training": baseline["seconds_per_training"],
            "order": [candidate["order_in_pair"], baseline["order_in_pair"]],
            "tcap_average_watts": candidate["average_watts"],
            "eager_average_watts": baseline["average_watts"],
            "tcap_maximum_temperature_c": _sample_maximum_temperature(candidate),
            "eager_maximum_temperature_c": _sample_maximum_temperature(baseline),
        })
    ratios = tuple(item["ratio_tcap_over_eager"] for item in pairs)
    if len(ratios) >= 2:
        low, high = paired_bootstrap_ci(ratios, seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES)
    else:
        low = high = None
    median = statistics.median(ratios) if ratios else None
    complete = len(pairs) == PAIR_COUNT
    t_temperatures = [item["tcap_maximum_temperature_c"] for item in pairs if item["tcap_maximum_temperature_c"] is not None]
    e_temperatures = [item["eager_maximum_temperature_c"] for item in pairs if item["eager_maximum_temperature_c"] is not None]
    thermal_asymmetry = abs(statistics.median(t_temperatures) - statistics.median(e_temperatures)) if len(t_temperatures) == len(pairs) and len(e_temperatures) == len(pairs) and pairs else None
    thermal_parity = bool(thermal_asymmetry is not None and thermal_asymmetry <= 3.0)
    source = read_json(directory / "hwinfo_source.json")
    sensor = source["inspection"]["selected_energy_sensor"]
    exploratory_source = sensor.get("provenance") != "hwinfo_reported_cpu_package"
    advantage = bool(complete and thermal_parity and median is not None and median < 1 and high is not None and high < 1)
    no_advantage = bool(complete and thermal_parity and median is not None and median >= 1 and low is not None and low >= 1)
    blocker = read_json(directory / "campaign_blocker.json") if (directory / "campaign_blocker.json").exists() else None
    if complete and exploratory_source:
        terminal = "EXPLORATORY_HWINFO_ENERGY_ONLY"
    elif advantage:
        terminal = "PASS_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS"
    elif no_advantage:
        terminal = "FAIL_NO_CPU_PACKAGE_ENERGY_ADVANTAGE_HWINFO_WINDOWS"
    elif complete:
        terminal = "INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS"
    else:
        terminal = "BLOCKED_PHYSICAL_INSTRUMENT"
    candidate_values = [item["tcap_joules_per_training"] for item in pairs]
    baseline_values = [item["eager_joules_per_training"] for item in pairs]
    analysis = {
        "schema": ANALYSIS_SCHEMA,
        "campaign_id": directory.name,
        "terminal_state": terminal,
        "scientific_scope": "HWiNFO-reported CPU package energy on bare-metal Windows",
        "valid_pairs": len(pairs),
        "rejected_samples": len(list((directory / "rejected").glob("*.json"))),
        "complete_design": complete,
        "pairs": pairs,
        "median_joules_per_training": {
            TCAP_IMPLEMENTATION: statistics.median(candidate_values) if candidate_values else None,
            EAGER_IMPLEMENTATION: statistics.median(baseline_values) if baseline_values else None,
        },
        "median_ratio_tcap_over_eager": median,
        "paired_bootstrap_ci95": {"lower": low, "upper": high, "seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES},
        "exact_sign_test": exact_sign_test(candidate_values, baseline_values) if pairs else None,
        "material_improvement_at_least_10_percent": bool(median is not None and 1 - median >= 0.10),
        "thermal_parity": {
            "passed": thermal_parity,
            "median_maximum_temperature_asymmetry_c": thermal_asymmetry,
            "frozen_limit_c": 3.0,
        },
        "sensor_provenance": sensor,
        "equivalence": read_json(directory / "equivalence" / "gate.json"),
        "limitations": {
            "total_system_wall": "BLOCKED_PHYSICAL_INSTRUMENT",
            "casulo_native_energy": "BLOCKED_PHYSICAL_INSTRUMENT",
            "inductor": "NOT_TESTED",
            "gpu_tpu_datacenter": "NOT_MEASURED",
            "external_electrical_calibration": "NOT_PRESENT",
        },
        "outliers_removed": False,
        "blocker": blocker,
        "implementation_summary": {
            TCAP_IMPLEMENTATION: _implementation_summary(pairs, "tcap"),
            EAGER_IMPLEMENTATION: _implementation_summary(pairs, "eager"),
        },
    }
    write_json(directory / "analysis.json", analysis)
    return analysis


def render_hwinfo_report(directory: Path, analysis: dict[str, Any] | None = None) -> Path:
    value = analysis or read_json(directory / "analysis.json")
    sensor = read_json(directory / "hwinfo_source.json")["inspection"]["selected_energy_sensor"]
    calibration = read_json(directory / "calibration.json")
    tcap_joules = value["median_joules_per_training"][TCAP_IMPLEMENTATION]
    eager_joules = value["median_joules_per_training"][EAGER_IMPLEMENTATION]
    ratio = value["median_ratio_tcap_over_eager"]
    ci = value["paired_bootstrap_ci95"]
    idle = calibration.get("idle", {})
    lines = [
        "# Campanha energética HWiNFO: TCAP × PyTorch Eager",
        "",
        f"**Estado científico:** `{value['terminal_state']}`",
        "",
        "## Escopo autorizado",
        "",
        "HWiNFO-reported CPU package energy on bare-metal Windows. O resultado não mede energia total na tomada nem energia do Casulo Native.",
        "",
        "## Instrumento e desenho",
        "",
        f"- Campo literal: `{sensor['literal_name']}` ({sensor['unit']})",
        "- Conversão: integração trapezoidal nos timestamps reais",
        f"- Amostragem mediana: {read_json(directory / 'hwinfo_source.json')['inspection']['sampling']['median_seconds']:.6f} s",
        f"- Pares válidos: {value['valid_pairs']}/{PAIR_COUNT}",
        f"- Rejeitados: {value['rejected_samples']}",
        "- Épocas por treinamento: 400",
        f"- Threads/afinidade: {THREADS} / {list(AFFINITY)}",
        f"- Idle medido: {_format_number(idle.get('average_watts'))} W",
        "",
        "## Resultado primário",
        "",
        f"- TCAP: {_format_number(tcap_joules)} J/treinamento",
        f"- PyTorch Eager: {_format_number(eager_joules)} J/treinamento",
        f"- Razão TCAP/Eager: {_format_number(ratio)}",
        f"- IC bootstrap pareado 95%: [{_format_number(ci.get('lower'))}, {_format_number(ci.get('upper'))}]",
        f"- Teste de sinais: `{json.dumps(value['exact_sign_test'], ensure_ascii=False)}`",
        "",
        "## Equivalência",
        "",
        f"Gate: `{value['equivalence']['status']}`; tolerância absoluta congelada 1e-9; mesmas 400 épocas, dataset, parâmetros iniciais, precisão e threads.",
        "",
        "## Limites invariantes",
        "",
        "- `TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`",
        "- `CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`",
        "- Nenhuma alegação sobre Inductor, datacenter, GPU/TPU ou potência elétrica calibrada externamente.",
        "- Nenhum outlier foi removido após observação.",
        "",
    ]
    if value.get("blocker"):
        lines.extend([
            "## Bloqueio físico observado",
            "",
            f"`{value['blocker']['reason_code']}`: {value['blocker']['summary']}",
            "",
            f"Ação humana única restante: {value['blocker']['single_physical_action']}",
            "",
        ])
    path = directory / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def finalize_source_and_seal(directory: Path, csv_path: Path) -> dict[str, Any]:
    snapshot = read_shared_snapshot(csv_path)
    (directory / "source_csv_final.sha256").write_text(
        f"{snapshot.sha256}  {Path(csv_path).name} bytes=0:{snapshot.bytes_read}\n",
        encoding="ascii", newline="\n",
    )
    markers = _read_jsonl(directory / "benchmark_markers.jsonl")
    bounds = [datetime.fromisoformat(item["utc"]) for item in markers if item.get("event") in {"idle_start", "segment_start", "segment_end", "idle_end"}]
    if bounds:
        from .hwinfo import extract_interval_csv

        extracted = extract_interval_csv(snapshot, min(bounds), max(bounds))
        (directory / "extracted_campaign.csv").write_text(extracted, encoding="utf-8", newline="")
    files = [path for path in directory.rglob("*") if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}]
    manifest_files = [{"path": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(files)]
    manifest = {"schema": "casulo-hwinfo-energy-manifest/1.0", "campaign_id": directory.name, "sealed_at_utc": _utc(), "files": manifest_files}
    write_json(directory / "MANIFEST.json", manifest)
    files_with_manifest = [*files, directory / "MANIFEST.json"]
    (directory / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(directory).as_posix()}\n" for path in sorted(files_with_manifest)),
        encoding="ascii", newline="\n",
    )
    return {"manifest_sha256": sha256_file(directory / "MANIFEST.json"), "sha256s_sha256": sha256_file(directory / "SHA256SUMS"), "source_final_sha256": snapshot.sha256}


def verify_hwinfo_seal(directory: Path) -> dict[str, Any]:
    root = Path(directory).resolve()
    manifest = read_json(root / "MANIFEST.json")
    errors = []
    for item in manifest.get("files", []):
        path = (root / item["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append(f"path escapes campaign: {item['path']}")
            continue
        if not path.is_file():
            errors.append(f"missing: {item['path']}")
        elif path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            errors.append(f"hash_or_size_mismatch: {item['path']}")
    expected = {}
    for line in (root / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, relative = line.split("  ", 1)
        expected[relative] = digest
    for relative, digest in expected.items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            errors.append(f"sha256s_mismatch: {relative}")
    return {"status": "PASS" if not errors else "FAIL", "files": len(manifest.get("files", [])), "errors": errors}


def _idle_window(csv_path: Path, marker_path: Path, *, seconds: float) -> dict[str, Any]:
    _wait_safe_start(csv_path)
    start = datetime.now(timezone.utc)
    _append_jsonl(marker_path, _marker("idle_start", "calibration", "idle", None))
    deadline = time.monotonic() + seconds
    observations = []
    while time.monotonic() < deadline:
        state = _live_guard(csv_path, during_load=False)
        observations.append(state)
        if not state["logger_live"] or state["throttling"]:
            raise RuntimeError("idle calibration guard failed: " + state["reason_code"])
        time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
    end = datetime.now(timezone.utc)
    _append_jsonl(marker_path, _marker("idle_end", "calibration", "idle", None))
    _wait_for_bracketing_sample(csv_path, end)
    _, parsed, _ = inspect_file(csv_path)
    window = integrate_window(parsed, start, end, minimum_samples=60)
    if window.status != "PASS":
        raise RuntimeError("idle HWiNFO window rejected: " + window.reason_code)
    return {**window.to_dict(), "observations": observations}


def _run_sample(
    directory: Path,
    csv_path: Path,
    worker: PersistentWorker,
    total_k: int,
    segment_k: int,
    session_id: str,
    pair_id: str,
    order: int,
    tcap_path: Path,
) -> dict[str, Any]:
    remaining = total_k
    segments = []
    last_result = None
    sample_started = time.monotonic_ns()
    while remaining > 0:
        count = min(segment_k, remaining)
        segment = _run_segment(directory, csv_path, worker, count, pair_id, f"{order}-{len(segments)+1:03d}", tcap_path)
        segments.append(segment)
        last_result = segment["worker_result"]
        remaining -= count
    duration = sum(item["elapsed_seconds"] for item in segments)
    energy = sum(item["energy_joules"] for item in segments)
    samples = sum(item["sample_count"] for item in segments)
    protocol = read_json(directory / "protocol.json")
    accepted = (
        duration >= protocol["minimum_measured_seconds_per_sample"]
        and samples >= protocol["minimum_hwinfo_samples_per_sample"]
        and all(item["accepted"] for item in segments)
        and last_result is not None
    )
    reason = "accepted" if accepted else "aggregate_duration_samples_or_segment_gate_failed"
    return {
        "schema": SAMPLE_SCHEMA,
        "campaign_id": directory.name,
        "session_id": session_id,
        "pair_id": pair_id,
        "order_in_pair": order,
        "implementation": worker.implementation,
        "workload": WORKLOAD,
        "epochs_per_training": 400,
        "K": total_k,
        "segments": segments,
        "measured_execution_seconds": duration,
        "energy_joules": energy,
        "joules_per_training": energy / total_k,
        "seconds_per_training": duration / total_k,
        "average_watts": energy / duration,
        "hwinfo_sample_count": samples,
        "accepted": accepted,
        "reason_code": reason,
        "equivalence": read_json(directory / "equivalence" / "gate.json")["status"],
        "numeric_result": last_result,
        "monotonic_ns_start": sample_started,
        "monotonic_ns_end": time.monotonic_ns(),
        "compilation_included": False,
        "initialization_included": False,
        "physical_measurement": True,
        "source_provenance": "HWiNFO-reported CPU package power integrated over real timestamps",
        "hashes": {**read_json(directory / "input_hashes.json"), "executable_sha256": _worker_hash(directory, worker.implementation)},
    }


def _run_segment(
    directory: Path,
    csv_path: Path,
    worker: PersistentWorker,
    count: int,
    pair_id: str,
    segment_id: str,
    tcap_path: Path,
) -> dict[str, Any]:
    before = _wait_safe_start(csv_path)
    start_utc = datetime.now(timezone.utc)
    start_mono = time.monotonic_ns()
    _append_jsonl(directory / "benchmark_markers.jsonl", _marker("segment_start", pair_id, segment_id, worker))
    try:
        result, observations = worker.run(count, timeout_seconds=MAXIMUM_CONTINUOUS_SECONDS + 10, guard=lambda: _live_guard(csv_path, during_load=True))
    except Exception as exc:
        rejection = {
            "schema": "casulo-hwinfo-rejected-segment/1.0",
            "pair_id": pair_id,
            "segment_id": segment_id,
            "implementation": worker.implementation,
            "K": count,
            "timestamp_utc_start": start_utc.isoformat(),
            "timestamp_utc_rejected": _utc(),
            "reason_code": f"{type(exc).__name__}:{exc}",
            "promoted_to_scientific_sample": False,
        }
        write_json(directory / "rejected" / f"{pair_id}-{segment_id}-{time.monotonic_ns()}.json", rejection)
        raise
    end_mono = time.monotonic_ns()
    end_utc = datetime.now(timezone.utc)
    _append_jsonl(directory / "benchmark_markers.jsonl", _marker("segment_end", pair_id, segment_id, worker))
    result = _complete_native_result(result, tcap_path)
    elapsed = float(result["elapsed_seconds"])
    if elapsed > MAXIMUM_CONTINUOUS_SECONDS:
        write_json(directory / "rejected" / f"{pair_id}-{segment_id}-{time.monotonic_ns()}.json", {
            "schema": "casulo-hwinfo-rejected-segment/1.0",
            "pair_id": pair_id,
            "segment_id": segment_id,
            "implementation": worker.implementation,
            "K": count,
            "elapsed_seconds": elapsed,
            "reason_code": "maximum_continuous_seconds_exceeded",
            "promoted_to_scientific_sample": False,
        })
        raise RuntimeError("physical_guard:maximum_continuous_seconds_exceeded")
    _wait_for_bracketing_sample(csv_path, end_utc)
    _, parsed, _ = inspect_file(csv_path)
    window = integrate_window(parsed, start_utc, end_utc, minimum_samples=2)
    after = _live_guard(csv_path, during_load=False)
    accepted = window.status == "PASS" and after["safe_after_load"] and result["status"] == "PASS"
    return {
        "segment_id": segment_id,
        "implementation": worker.implementation,
        "K": count,
        "timestamp_utc_start": start_utc.isoformat(),
        "timestamp_utc_end": end_utc.isoformat(),
        "monotonic_ns_start": start_mono,
        "monotonic_ns_end": end_mono,
        "elapsed_seconds": elapsed,
        "energy_joules": window.energy_joules,
        "average_watts": window.average_watts,
        "sample_count": window.sample_count,
        "median_interval_seconds": window.median_interval_seconds,
        "maximum_gap_seconds": window.maximum_gap_seconds,
        "coverage": window.coverage,
        "accepted": accepted,
        "reason_code": "accepted" if accepted else f"{window.reason_code}:{after['reason_code']}",
        "thermal_before": before,
        "thermal_during": observations,
        "thermal_after": after,
        "worker_result": result,
    }


def _live_guard(csv_path: Path, *, during_load: bool) -> dict[str, Any]:
    key = str(Path(csv_path).resolve())
    try:
        with _LIVE_TAILS_LOCK:
            reader = _LIVE_TAILS.get(key)
            if reader is None:
                reader = HWiNFOLiveTail(Path(csv_path).resolve())
                reader.initialize()
                _LIVE_TAILS[key] = reader
            header, values, latest_timestamp, source_size = reader.read_latest()
    except (OSError, UnicodeError, HWiNFOError, csv.Error):
        return {"logger_live": False, "safe_during_load": False, "safe_after_load": False, "reason_code": "source_unavailable"}
    return _guard_state(header, values, latest_timestamp, source_size, "bounded-live-tail-v1")


def incremental_guard(reader: HWiNFOIncrementalWatcher) -> dict[str, Any]:
    try:
        header, values, latest_timestamp, source_size = reader.read_latest()
    except (OSError, UnicodeError, HWiNFOError, csv.Error):
        return {"logger_live": False, "safe_during_load": False, "safe_after_load": False, "reason_code": "source_unavailable"}
    return _guard_state(header, values, latest_timestamp, source_size, "append-only-incremental-v1")


def _guard_state(
    header: tuple[str, ...],
    values: tuple[str, ...],
    latest_timestamp: datetime,
    source_size: int,
    reader_name: str,
) -> dict[str, Any]:
    age = (datetime.now(timezone.utc) - latest_timestamp).total_seconds()
    normalized = [_normalize(item) for item in header]
    temperature = _first_numeric(values, normalized, lambda value: "temperaturas centrais" in value or ("cpu package" in value and "c" in value and "power" not in value))
    throttle_values = [
        values[index]
        for index, value in enumerate(normalized)
        if ("estrangulamento termico" in value or "thermal throttling" in value)
        and "maximum" not in value
        and "maximo" not in value
    ]
    throttling = any(_truthy(item) for item in throttle_values)
    battery_w = _first_numeric(values, normalized, lambda value: "taxa de carga" in value or "battery charge rate" in value)
    battery_percent = _first_numeric(values, normalized, lambda value: "nivel de carga" in value or "battery level" in value)
    frequency_mhz = _first_numeric(values, normalized, lambda value: ("relogios centrais" in value or "core clocks" in value) and "mhz" in value)
    ac_connected, battery_state = _windows_power_state()
    logger_live = -3 <= age <= 10
    if not logger_live:
        reason = "logger_stale_or_clock_mismatch"
    elif ac_connected is not True:
        reason = "ac_power_not_confirmed"
    elif temperature is None:
        reason = "trusted_cpu_temperature_unavailable"
    elif throttling:
        reason = "thermal_throttling_detected"
    elif temperature >= HARD_STOP_C:
        reason = "hard_temperature_limit"
    elif temperature >= SOFT_STOP_C:
        reason = "soft_temperature_limit"
    elif temperature >= WARNING_C:
        reason = "warning_temperature_limit"
    else:
        reason = "safe"
    return {
        "observed_at_utc": _utc(),
        "hwinfo_timestamp_utc": latest_timestamp.isoformat(),
        "logger_age_seconds": age,
        "logger_live": logger_live,
        "temperature_c": temperature,
        "throttling": throttling,
        "battery_charge_rate_w": battery_w,
        "battery_percent": battery_percent,
        "battery_state": battery_state,
        "ac_connected": ac_connected,
        "frequency_mhz": frequency_mhz,
        "safe_during_load": reason == "safe",
        "safe_after_load": reason == "safe",
        "ready_to_start": reason == "safe" and temperature is not None and temperature < RESUME_BELOW_C,
        "reason_code": reason,
        "source_last_size": source_size,
        "watchdog_reader": reader_name,
    }


def _wait_safe_start(csv_path: Path, *, timeout_seconds: float = 600.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    consecutive = 0
    previous_timestamp = None
    last = None
    while time.monotonic() < deadline:
        state = _live_guard(csv_path, during_load=False)
        last = state
        timestamp = state.get("hwinfo_timestamp_utc")
        if state.get("ready_to_start") and timestamp != previous_timestamp:
            consecutive += 1
            previous_timestamp = timestamp
            if consecutive >= 3:
                return state
        elif not state.get("ready_to_start"):
            consecutive = 0
        if state.get("throttling") or (state.get("temperature_c") or 0) >= WARNING_C:
            raise RuntimeError("physical_guard:" + state["reason_code"])
        time.sleep(1.0)
    raise RuntimeError("physical_guard:cooldown_timeout:" + str(last))


def _wait_for_bracketing_sample(csv_path: Path, boundary: datetime, *, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _, parsed, _ = inspect_file(csv_path)
        if parsed.rows and parsed.rows[-1].timestamp_utc >= boundary:
            return
        time.sleep(0.5)
    raise RuntimeError("HWiNFO logger did not bracket benchmark boundary")


def _complete_native_result(result: dict[str, Any], tcap_path: Path) -> dict[str, Any]:
    if result["implementation"] != TCAP_IMPLEMENTATION:
        return result
    from .hwinfo_workers import _predictions, load_workload

    _, canary_raw, canary = load_workload(tcap_path)
    parameters = tuple(float(item) for item in result["parameters"])
    predictions = _predictions(canary, parameters)
    numeric = [result["loss"]["initial"], result["loss"]["final"], *parameters, *predictions]
    return {
        **result,
        "dataset_sha256": hashlib.sha256(canary_raw).hexdigest(),
        "predictions": list(predictions),
        "numeric_output_sha256": sha256_bytes(canonical_bytes(numeric)),
    }


def _schedule() -> list[dict[str, Any]]:
    return [
        {
            "pair_id": f"pair-{index:02d}",
            "order": [TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION] if index % 2 else [EAGER_IMPLEMENTATION, TCAP_IMPLEMENTATION],
        }
        for index in range(1, PAIR_COUNT + 1)
    ]


def _completed_pairs(directory: Path) -> set[str]:
    values: dict[str, set[str]] = {}
    for path in (directory / "raw").glob("pair-*.json"):
        sample = read_json(path)
        if sample.get("accepted"):
            values.setdefault(sample["pair_id"], set()).add(sample["implementation"])
    return {pair for pair, implementations in values.items() if implementations == {TCAP_IMPLEMENTATION, EAGER_IMPLEMENTATION}}


def _marker(event: str, pair_id: str, segment_id: str, worker: PersistentWorker | None) -> dict[str, Any]:
    now = datetime.now().astimezone()
    return {
        "event": event,
        "campaign_phase": "calibration" if pair_id == "calibration" else "measurement",
        "pair_id": pair_id,
        "segment_id": segment_id,
        "implementation": worker.implementation if worker else "idle",
        "pid": worker.pid if worker else os.getpid(),
        "utc": now.astimezone(timezone.utc).isoformat(),
        "local": now.isoformat(),
        "monotonic_ns": time.monotonic_ns(),
    }


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _first_numeric(values: tuple[str, ...], normalized: list[str], match) -> float | None:
    for index, name in enumerate(normalized):
        if match(name):
            try:
                value = float(values[index].strip().replace(",", "."))
            except (ValueError, IndexError):
                continue
            if math.isfinite(value):
                return value
    return None


def _truthy(value: str) -> bool:
    return _normalize(value) in {
        "yes",
        "sim",
        "true",
        "verdadeiro",
        "1",
        "active",
        "ativo",
    }


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join("".join(character if character.isalnum() else " " for character in text).split())


def _dataset_sha(tcap_path: Path) -> str:
    from .hwinfo_workers import load_workload

    return hashlib.sha256(load_workload(tcap_path)[1]).hexdigest()


def _windows_power_state() -> tuple[bool | None, str | None]:
    try:
        import psutil

        battery = psutil.sensors_battery()
    except Exception:
        return None, None
    if battery is None:
        return None, None
    state = "AC_CONNECTED" if battery.power_plugged else "BATTERY"
    return bool(battery.power_plugged), state


def _infer_source_history(path: Path, inspection: dict[str, Any]) -> dict[str, Any]:
    import re

    folder_dates = re.findall(r"20\d{2}-\d{2}-\d{2}", str(path))
    first = inspection.get("first_timestamp_utc")
    first_date = datetime.fromisoformat(first).date().isoformat() if first else None
    folder_date = folder_dates[-1] if folder_dates else None
    overwritten = bool(folder_date and first_date and first_date > folder_date)
    return {
        "folder_date": folder_date,
        "first_sample_date_utc": first_date,
        "header_count": inspection.get("header_count"),
        "session_count": inspection.get("session_count"),
        "prior_historical_content_present": bool(inspection.get("session_count", 0) > 1),
        "logger_restarted_or_overwrote_older_named_file": overwritten,
        "inference_basis": "folder date precedes first surviving sample" if overwritten else "no overwrite inference",
    }


def _worker_hash(directory: Path, implementation: str) -> str:
    if implementation == TCAP_IMPLEMENTATION:
        return read_json(directory / "worker_build.json")["executable_sha256"]
    return sha256_file(Path(sys.executable))


def _slug(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-").lower()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_number(value: Any) -> str:
    return "unavailable" if value is None else f"{float(value):.9f}"


def _sample_maximum_temperature(sample: dict[str, Any]) -> float | None:
    values = []
    for segment in sample.get("segments", []):
        for key in ("thermal_before", "thermal_after"):
            value = segment.get(key, {}).get("temperature_c")
            if isinstance(value, (int, float)):
                values.append(float(value))
        for observation in segment.get("thermal_during", []):
            value = observation.get("temperature_c")
            if isinstance(value, (int, float)):
                values.append(float(value))
    return max(values) if values else None


def _implementation_summary(pairs: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    if not pairs:
        return None
    temperatures = [item[f"{prefix}_maximum_temperature_c"] for item in pairs if item[f"{prefix}_maximum_temperature_c"] is not None]
    return {
        "median_joules_per_training": statistics.median(item[f"{prefix}_joules_per_training"] for item in pairs),
        "median_seconds_per_training": statistics.median(item[f"{prefix}_seconds_per_training"] for item in pairs),
        "median_average_watts": statistics.median(item[f"{prefix}_average_watts"] for item in pairs),
        "median_maximum_temperature_c": statistics.median(temperatures) if temperatures else None,
    }
