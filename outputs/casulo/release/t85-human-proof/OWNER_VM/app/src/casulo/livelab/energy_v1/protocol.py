from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import PROTOCOL_SCHEMA, SCHEDULE_SCHEMA, canonical_bytes, read_json, sha256_bytes, write_json


@dataclass(frozen=True, slots=True)
class EnergyProtocol:
    campaign_id: str
    candidate: str
    baseline: str
    workload: str
    energy_domain: str
    sessions: int = 3
    pairs_per_session: int = 21
    warmups: int = 3
    seed: int = 260807
    bootstrap_seed: int = 26080701
    bootstrap_resamples: int = 20_000
    threads: int = 4
    affinity: tuple[int, ...] = (0, 1, 2, 3)
    maximum_temperature_c: float = 55.0
    maximum_thermal_drift_c: float = 3.0
    cooldown_temperature_c: float = 55.0
    minimum_rapl_window_seconds: float = 10.0
    preferred_rapl_window_seconds: float = 30.0
    minimum_wall_window_seconds: float = 60.0
    maximum_wall_window_seconds: float = 120.0
    K: dict[str, int] = field(default_factory=dict)
    include_compilation_metric: bool = True
    exclude_compilation_metric: bool = True
    outlier_removal: str = "forbidden"
    equivalence_required: bool = True
    physical_only: bool = True
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema: str = PROTOCOL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PROTOCOL_SCHEMA or not self.campaign_id:
            raise ValueError("invalid energy protocol identity")
        if self.energy_domain not in {"CPU_PACKAGE_RAPL", "TOTAL_SYSTEM_WALL"}:
            raise ValueError("invalid physical energy domain")
        if self.sessions < 3 or self.pairs_per_session < 21 or self.warmups != 3:
            raise ValueError("confirmatory design requires 3 sessions, 21 pairs and 3 warmups")
        if self.threads < 1 or len(self.affinity) != self.threads or min(self.affinity) < 0:
            raise ValueError("thread and affinity contract differs")
        if self.outlier_removal != "forbidden" or not self.equivalence_required or not self.physical_only:
            raise ValueError("scientific invariants cannot be relaxed")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in self.K.values()):
            raise ValueError("all K values must be positive integers")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["affinity"] = list(self.affinity)
        return value

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_bytes(self.to_dict()))


def deterministic_schedule(protocol: EnergyProtocol) -> dict[str, Any]:
    rng = random.Random(protocol.seed)
    sessions = []
    for session in range(1, protocol.sessions + 1):
        pairs = []
        # One seeded coin flip chooses the first order; alternation then keeps
        # AB/BA balanced (difference at most one for an odd pair count).
        first_ab = bool(rng.getrandbits(1))
        for pair in range(1, protocol.pairs_per_session + 1):
            ab = first_ab if pair % 2 else not first_ab
            order = [protocol.baseline, protocol.candidate] if ab else [protocol.candidate, protocol.baseline]
            pairs.append({"pair_id": f"S{session:02d}-P{pair:03d}", "order": order})
        sessions.append({"session_id": f"S{session:02d}", "pairs": pairs})
    return {
        "schema": SCHEDULE_SCHEMA,
        "campaign_id": protocol.campaign_id,
        "protocol_sha256": protocol.sha256,
        "seed": protocol.seed,
        "frozen_before_results": True,
        "sessions": sessions,
    }


def freeze_protocol(directory: Path, protocol: EnergyProtocol) -> tuple[Path, Path]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    protocol_path = root / "protocol.json"
    schedule_path = root / "schedule.json"
    if protocol_path.exists() or schedule_path.exists():
        raise FileExistsError("protocol or schedule already frozen")
    write_json(protocol_path, protocol.to_dict())
    write_json(schedule_path, deterministic_schedule(protocol))
    return protocol_path, schedule_path


def load_protocol(path: Path) -> EnergyProtocol:
    value = read_json(path)
    value["affinity"] = tuple(value["affinity"])
    return EnergyProtocol(**value)
