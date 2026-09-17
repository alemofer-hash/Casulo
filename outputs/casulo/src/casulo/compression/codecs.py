from __future__ import annotations

import lzma
import zlib
from dataclasses import dataclass


class CodecError(ValueError):
    """O payload não respeita o codec ou os limites declarados."""


@dataclass(frozen=True)
class EncodedChunk:
    codec: str
    payload: bytes


def encode_chunk(data: bytes, *, profile: str) -> EncodedChunk:
    if profile not in {"fast", "balanced", "max"}:
        raise CodecError(f"perfil de codec desconhecido: {profile}")

    level = 1 if profile == "fast" else 9
    candidates = [
        EncodedChunk("raw", data),
        EncodedChunk("zlib", zlib.compress(data, level)),
    ]
    if profile == "max":
        candidates.append(EncodedChunk("lzma", lzma.compress(data, preset=6)))

    priority = {"raw": 0, "zlib": 1, "lzma": 2}
    best = min(
        candidates,
        key=lambda candidate: (len(candidate.payload), priority[candidate.codec]),
    )
    return best if len(best.payload) < len(data) else EncodedChunk("raw", data)


def decode_chunk(payload: bytes, *, codec: str, expected_size: int) -> bytes:
    if expected_size < 0:
        raise CodecError("tamanho descomprimido negativo")

    try:
        if codec == "raw":
            decoded = payload
        elif codec == "zlib":
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(payload, expected_size + 1)
            decoded += decoder.flush()
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise CodecError("payload zlib truncado ou com dados excedentes")
        elif codec == "lzma":
            decoder = lzma.LZMADecompressor()
            decoded = decoder.decompress(payload, max_length=expected_size + 1)
            if not decoder.eof or decoder.unused_data:
                raise CodecError("payload lzma truncado ou com dados excedentes")
        else:
            raise CodecError(f"codec não permitido: {codec}")
    except (lzma.LZMAError, zlib.error) as exc:
        raise CodecError(f"payload {codec} inválido") from exc

    if len(decoded) != expected_size:
        raise CodecError(
            f"tamanho descomprimido divergente: esperado {expected_size}, "
            f"obtido {len(decoded)}"
        )
    return decoded
