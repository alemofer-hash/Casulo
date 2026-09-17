from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import Iterable, Mapping

from .casv_tile_ir import MAX_TILE_CANONICAL_BYTES
from .casv_temporal_ir import TEMPORAL_TILE_MODES


MOTION_VECTOR = struct.Struct(">bb")
MAX_MOTION_RADIUS = 32
MAX_MOTION_FINALISTS = 16
MOTION_TILE_MODES = (
    *TEMPORAL_TILE_MODES,
    "MOTION_XOR_ZLIB",
    "MOTION_SUB_ZLIB",
)


class CASVMotionIRError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MotionCandidates:
    payloads: Mapping[str, bytes]
    vectors: Mapping[str, tuple[int, int]]
    reference_sha256: Mapping[str, str]
    references: Mapping[str, bytes]
    scores: Mapping[str, int]
    examined_vectors: int
    finalist_vectors: tuple[tuple[int, int], ...]
    score_stride_pixels: int

    def validate(self, expected_bytes: int, radius: int) -> None:
        expected_modes = {"MOTION_XOR_ZLIB", "MOTION_SUB_ZLIB"}
        if set(self.payloads) not in (set(), expected_modes):
            raise CASVMotionIRError("motion candidate family is incomplete")
        if not 1 <= expected_bytes <= MAX_TILE_CANONICAL_BYTES:
            raise CASVMotionIRError("motion tile size is outside bounds")
        if not 1 <= radius <= MAX_MOTION_RADIUS:
            raise CASVMotionIRError("motion radius is outside bounds")
        if not self.payloads:
            if any(
                (
                    self.vectors,
                    self.reference_sha256,
                    self.references,
                    self.scores,
                    self.finalist_vectors,
                    self.examined_vectors,
                )
            ):
                raise CASVMotionIRError("empty motion family carries evidence")
            return
        if (
            set(self.vectors) != expected_modes
            or set(self.reference_sha256) != expected_modes
            or set(self.references) != expected_modes
            or set(self.scores) != expected_modes
            or self.examined_vectors <= 0
            or not self.finalist_vectors
        ):
            raise CASVMotionIRError("motion evidence family is incomplete")
        for mode in expected_modes:
            dx, dy = self.vectors[mode]
            if (dx, dy) == (0, 0) or abs(dx) > radius or abs(dy) > radius:
                raise CASVMotionIRError("motion vector is outside declared bounds")
            if len(self.payloads[mode]) <= MOTION_VECTOR.size:
                raise CASVMotionIRError("motion candidate payload is truncated")
            payload_dx, payload_dy = MOTION_VECTOR.unpack_from(self.payloads[mode])
            if (payload_dx, payload_dy) != (dx, dy):
                raise CASVMotionIRError("motion vector prefix differs")
            reference = self.references[mode]
            if len(reference) != expected_bytes:
                raise CASVMotionIRError("motion reference length differs")
            if hashlib.sha256(reference).hexdigest() != self.reference_sha256[mode]:
                raise CASVMotionIRError("motion reference hash differs")


def _sample_value(payload: bytes, offset: int, bytes_per_pixel: int) -> int:
    if bytes_per_pixel == 2:
        return payload[offset] | payload[offset + 1] << 8
    raise CASVMotionIRError("sample value is only defined for 16-bit planes")


def sample_aware_sad(
    current: bytes,
    reference: bytes,
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
    stride_pixels: int,
) -> int:
    expected = width * height * bytes_per_pixel
    if len(current) != expected or len(reference) != expected or not current:
        raise CASVMotionIRError("motion score inputs differ from tile geometry")
    if bytes_per_pixel not in (2, 3):
        raise CASVMotionIRError("motion score pixel width is unsupported")
    if not 1 <= stride_pixels <= max(width, height):
        raise CASVMotionIRError("motion score stride is outside bounds")
    score = 0
    row_bytes = width * bytes_per_pixel
    for y in range(0, height, stride_pixels):
        row = y * row_bytes
        for x in range(0, width, stride_pixels):
            offset = row + x * bytes_per_pixel
            if bytes_per_pixel == 2:
                score += abs(
                    _sample_value(current, offset, bytes_per_pixel)
                    - _sample_value(reference, offset, bytes_per_pixel)
                )
            else:
                for channel in range(3):
                    score += abs(current[offset + channel] - reference[offset + channel])
    return score


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=True))


def _subtract(left: bytes, right: bytes) -> bytes:
    return bytes((a - b) & 0xFF for a, b in zip(left, right, strict=True))


def build_motion_candidates(
    current: bytes,
    references: Iterable[tuple[int, int, bytes]],
    *,
    width: int,
    height: int,
    bytes_per_pixel: int,
    radius: int,
    score_stride_pixels: int = 4,
    finalists: int = 4,
) -> MotionCandidates:
    expected = width * height * bytes_per_pixel
    if len(current) != expected or not 1 <= expected <= MAX_TILE_CANONICAL_BYTES:
        raise CASVMotionIRError("motion current tile differs from geometry")
    if not 1 <= radius <= MAX_MOTION_RADIUS:
        raise CASVMotionIRError("motion radius is outside bounds")
    if not 1 <= finalists <= MAX_MOTION_FINALISTS:
        raise CASVMotionIRError("motion finalist count is outside bounds")

    ranked: list[tuple[tuple[int, int, int, int], bytes]] = []
    examined = 0
    seen: set[tuple[int, int]] = set()
    for dx, dy, reference in references:
        if type(dx) is not int or type(dy) is not int:
            raise CASVMotionIRError("motion vector is not integral")
        if (dx, dy) == (0, 0) or abs(dx) > radius or abs(dy) > radius:
            raise CASVMotionIRError("motion vector is outside declared bounds")
        if (dx, dy) in seen:
            raise CASVMotionIRError("motion vector is duplicated")
        seen.add((dx, dy))
        score = sample_aware_sad(
            current,
            reference,
            width=width,
            height=height,
            bytes_per_pixel=bytes_per_pixel,
            stride_pixels=score_stride_pixels,
        )
        key = (score, abs(dx) + abs(dy), dy, dx)
        ranked.append((key, reference))
        ranked.sort(key=lambda item: item[0])
        del ranked[finalists:]
        examined += 1

    if not ranked:
        empty = MotionCandidates(
            payloads={},
            vectors={},
            reference_sha256={},
            references={},
            scores={},
            examined_vectors=0,
            finalist_vectors=(),
            score_stride_pixels=score_stride_pixels,
        )
        empty.validate(expected, radius)
        return empty

    winners: dict[str, tuple[tuple[int, int, int, int, int], bytes, bytes]] = {}
    for key, reference in ranked:
        score, distance, dy, dx = key
        prefix = MOTION_VECTOR.pack(dx, dy)
        residuals = {
            "MOTION_XOR_ZLIB": _xor(current, reference),
            "MOTION_SUB_ZLIB": _subtract(current, reference),
        }
        for mode, residual in residuals.items():
            payload = prefix + zlib.compress(residual, level=9)
            candidate_key = (len(payload), score, distance, dy, dx)
            previous = winners.get(mode)
            if previous is None or candidate_key < previous[0]:
                winners[mode] = (candidate_key, payload, reference)

    payloads = {mode: value[1] for mode, value in winners.items()}
    vectors = {
        mode: (value[0][4], value[0][3]) for mode, value in winners.items()
    }
    references_by_mode = {mode: value[2] for mode, value in winners.items()}
    result = MotionCandidates(
        payloads=payloads,
        vectors=vectors,
        reference_sha256={
            mode: hashlib.sha256(reference).hexdigest()
            for mode, reference in references_by_mode.items()
        },
        references=references_by_mode,
        scores={mode: value[0][1] for mode, value in winners.items()},
        examined_vectors=examined,
        finalist_vectors=tuple((key[3], key[2]) for key, _reference in ranked),
        score_stride_pixels=score_stride_pixels,
    )
    result.validate(expected, radius)
    return result


def parse_motion_payload(stored: bytes, radius: int) -> tuple[int, int, bytes]:
    if len(stored) <= MOTION_VECTOR.size:
        raise CASVMotionIRError("motion payload is truncated")
    dx, dy = MOTION_VECTOR.unpack_from(stored)
    if (dx, dy) == (0, 0) or abs(dx) > radius or abs(dy) > radius:
        raise CASVMotionIRError("motion payload vector is outside bounds")
    return dx, dy, stored[MOTION_VECTOR.size :]


def restore_motion(mode: str, residual: bytes, reference: bytes) -> bytes:
    if len(residual) != len(reference) or not reference:
        raise CASVMotionIRError("motion restoration inputs differ in length")
    if mode == "MOTION_XOR_ZLIB":
        return _xor(residual, reference)
    if mode == "MOTION_SUB_ZLIB":
        return bytes(
            (value + base) & 0xFF
            for value, base in zip(residual, reference, strict=True)
        )
    raise CASVMotionIRError("unknown motion mode")


__all__ = [
    "CASVMotionIRError",
    "MAX_MOTION_FINALISTS",
    "MAX_MOTION_RADIUS",
    "MOTION_TILE_MODES",
    "MOTION_VECTOR",
    "MotionCandidates",
    "build_motion_candidates",
    "parse_motion_payload",
    "restore_motion",
    "sample_aware_sad",
]
