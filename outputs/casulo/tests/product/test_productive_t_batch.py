from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from casulo.t.productive import (
    ProductiveTBatchRequest,
    ProductiveTError,
    ProductiveTExecutor,
)
from casulo.t.v2_tcap import TcapV2Builder


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime" / "target" / "release" / (
    "casulo-t-runtime.exe" if os.name == "nt" else "casulo-t-runtime"
)
POLICY = ROOT / "examples" / "t-v2" / "compression_casv.t"


def request(index: int, generative: int, zlib: int, raw: int) -> ProductiveTBatchRequest:
    return ProductiveTBatchRequest(
        call_id=f"tile-{index:04d}",
        payload={
            "segment_index": index,
            "canonical_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
            "generative_candidate_available": True,
            "exact_generative_reconstruction": True,
            "no_foreign_bitstream": True,
            "generative_bytes": generative,
            "direct_zlib_bytes": zlib,
            "raw_bytes": raw,
            "cancelled": False,
        },
        surface_id="compression_casv_tile_selection",
        scope_id="casv:tile",
    )


def executor(tmp_path: Path) -> ProductiveTExecutor:
    built = TcapV2Builder().build(
        (POLICY,),
        tmp_path / "policy.tcap",
        entry_module="compression.casv",
        entry_function="decide",
    )
    return ProductiveTExecutor(RUNTIME, built.directory, tmp_path / "calls")


def test_batch_executes_independent_t_decisions_and_chains_receipts(tmp_path: Path) -> None:
    calls = executor(tmp_path).execute_batch(
        "compression.casv",
        "decide",
        (
            request(0, 7, 9, 11),
            request(1, 12, 8, 10),
            request(2, 14, 13, 9),
        ),
        batch_id="strip-0000",
    )

    assert [call.observable["result"]["value"] for call in calls] == [
        "GENERATIVE_EXACT",
        "CANONICAL_ZLIB",
        "CANONICAL_RAW",
    ]
    previous = "0" * 64
    for call in calls:
        assert call.receipt["previous_receipt_hash"] == previous
        previous = call.receipt["receipt_hash"]


def test_batch_rejects_duplicate_call_ids_before_runtime(tmp_path: Path) -> None:
    duplicate = request(0, 7, 9, 11)
    with pytest.raises(ProductiveTError, match="call_id duplicado"):
        executor(tmp_path).execute_batch(
            "compression.casv",
            "decide",
            (duplicate, duplicate),
            batch_id="duplicate",
        )


def test_batch_rejects_empty_work(tmp_path: Path) -> None:
    with pytest.raises(ProductiveTError, match="entre 1 e 65536"):
        executor(tmp_path).execute_batch(
            "compression.casv",
            "decide",
            (),
            batch_id="empty",
        )
