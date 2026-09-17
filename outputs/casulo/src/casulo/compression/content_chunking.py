from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


GEAR_TABLE = tuple(
    int.from_bytes(hashlib.sha256(f"casulo-gear-v1:{value}".encode("ascii")).digest()[:8], "big")
    for value in range(256)
)


@dataclass(frozen=True, slots=True)
class ChunkRange:
    offset: int
    length: int
    boundary: str


def _validate(min_bytes: int, avg_bytes: int, max_bytes: int) -> int:
    if not (0 < min_bytes <= avg_bytes <= max_bytes):
        raise ValueError("CDC requires 0 < min <= average <= maximum")
    if avg_bytes & (avg_bytes - 1):
        raise ValueError("CDC average must be a power of two")
    return avg_bytes - 1


def iter_content_defined_ranges(
    stream: BinaryIO,
    *,
    offset: int,
    length: int,
    min_bytes: int = 256 * 1024,
    avg_bytes: int = 1024 * 1024,
    max_bytes: int = 4 * 1024 * 1024,
    read_bytes: int = 256 * 1024,
) -> Iterator[ChunkRange]:
    mask = _validate(min_bytes, avg_bytes, max_bytes)
    if offset < 0 or length < 0 or read_bytes <= 0:
        raise ValueError("invalid CDC range")
    stream.seek(offset)
    remaining = length
    chunk_start = offset
    chunk_length = 0
    rolling = 0
    while remaining:
        block = stream.read(min(read_bytes, remaining))
        if not block:
            raise EOFError("source ended during CDC scan")
        remaining -= len(block)
        for value in block:
            rolling = ((rolling << 1) + GEAR_TABLE[value]) & 0xFFFFFFFFFFFFFFFF
            chunk_length += 1
            content_boundary = chunk_length >= min_bytes and (rolling & mask) == 0
            maximum_boundary = chunk_length >= max_bytes
            if content_boundary or maximum_boundary:
                yield ChunkRange(
                    offset=chunk_start,
                    length=chunk_length,
                    boundary="content" if content_boundary else "maximum",
                )
                chunk_start += chunk_length
                chunk_length = 0
                rolling = 0
    if chunk_length:
        yield ChunkRange(offset=chunk_start, length=chunk_length, boundary="end")


def ranges_for_file(
    path: str | Path,
    *,
    offset: int,
    length: int,
    min_bytes: int = 256 * 1024,
    avg_bytes: int = 1024 * 1024,
    max_bytes: int = 4 * 1024 * 1024,
) -> tuple[ChunkRange, ...]:
    with Path(path).resolve().open("rb", buffering=1024 * 1024) as stream:
        return tuple(
            iter_content_defined_ranges(
                stream,
                offset=offset,
                length=length,
                min_bytes=min_bytes,
                avg_bytes=avg_bytes,
                max_bytes=max_bytes,
            )
        )
