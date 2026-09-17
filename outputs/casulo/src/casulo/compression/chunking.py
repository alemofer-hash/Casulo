from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO


@dataclass(frozen=True)
class FixedChunkingPolicy:
    """Primeira política bounded; CDC nativo entra somente após profiling real."""

    chunk_size: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if not 64 * 1024 <= self.chunk_size <= 64 * 1024 * 1024:
            raise ValueError("chunk_size deve ficar entre 64 KiB e 64 MiB")

    def as_dict(self) -> dict[str, int | str]:
        return {"algorithm": "fixed-v1", "chunk_size": self.chunk_size}


def iter_fixed_chunks(source: BinaryIO, policy: FixedChunkingPolicy) -> Iterator[bytes]:
    while chunk := source.read(policy.chunk_size):
        yield chunk
