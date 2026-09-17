from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Mapping

from .casv_tile_ir import MAX_TILE_CANONICAL_BYTES


TEMPORAL_TILE_MODES = (
    "DC_XOR_ZLIB",
    "PAETH_ZLIB",
    "CANONICAL_ZLIB",
    "CANONICAL_RAW",
    "TEMPORAL_XOR_ZLIB",
    "TEMPORAL_SUB_ZLIB",
)


class CASVTemporalIRError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TemporalCandidates:
    reference_sha256: str
    payloads: Mapping[str, bytes]
    xor_zero_bytes: int
    subtract_zero_bytes: int

    def validate(self, expected_bytes: int) -> None:
        expected_modes = {"TEMPORAL_XOR_ZLIB", "TEMPORAL_SUB_ZLIB"}
        if set(self.payloads) != expected_modes:
            raise CASVTemporalIRError("temporal candidate family is incomplete")
        if not 1 <= expected_bytes <= MAX_TILE_CANONICAL_BYTES:
            raise CASVTemporalIRError("temporal tile size is outside bounds")
        if len(self.reference_sha256) != 64:
            raise CASVTemporalIRError("temporal reference hash is invalid")


def temporal_xor(current: bytes, previous: bytes) -> bytes:
    if len(current) != len(previous) or not current:
        raise CASVTemporalIRError("temporal XOR inputs differ in length")
    return bytes(left ^ right for left, right in zip(current, previous, strict=True))


def temporal_subtract(current: bytes, previous: bytes) -> bytes:
    if len(current) != len(previous) or not current:
        raise CASVTemporalIRError("temporal subtraction inputs differ in length")
    return bytes(
        (left - right) & 0xFF for left, right in zip(current, previous, strict=True)
    )


def build_temporal_candidates(current: bytes, previous: bytes) -> TemporalCandidates:
    import hashlib

    xor = temporal_xor(current, previous)
    subtract = temporal_subtract(current, previous)
    candidates = TemporalCandidates(
        reference_sha256=hashlib.sha256(previous).hexdigest(),
        payloads={
            "TEMPORAL_XOR_ZLIB": zlib.compress(xor, level=9),
            "TEMPORAL_SUB_ZLIB": zlib.compress(subtract, level=9),
        },
        xor_zero_bytes=xor.count(0),
        subtract_zero_bytes=subtract.count(0),
    )
    candidates.validate(len(current))
    return candidates


def restore_temporal(mode: str, residual: bytes, previous: bytes) -> bytes:
    if len(residual) != len(previous) or not previous:
        raise CASVTemporalIRError("temporal restoration inputs differ in length")
    if mode == "TEMPORAL_XOR_ZLIB":
        return bytes(
            left ^ right for left, right in zip(residual, previous, strict=True)
        )
    if mode == "TEMPORAL_SUB_ZLIB":
        return bytes(
            (left + right) & 0xFF
            for left, right in zip(residual, previous, strict=True)
        )
    raise CASVTemporalIRError("unknown temporal mode")


__all__ = [
    "CASVTemporalIRError",
    "TEMPORAL_TILE_MODES",
    "TemporalCandidates",
    "build_temporal_candidates",
    "restore_temporal",
    "temporal_subtract",
    "temporal_xor",
]
