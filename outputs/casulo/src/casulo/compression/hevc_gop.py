from __future__ import annotations

import hashlib
import os
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO, Sequence

from .mp4_hevc import primary_hevc_sample_layout


class HEVCGOPError(ValueError):
    """The HEVC access-unit stream is incomplete or structurally unsafe."""


def _read_exact(stream: BinaryIO, offset: int, length: int) -> bytes:
    stream.seek(offset)
    value = stream.read(length)
    if len(value) != length:
        raise HEVCGOPError(f"truncated HEVC read at {offset} ({length} bytes)")
    return value


def _nal_class(nal_type: int) -> str:
    if 0 <= nal_type <= 31:
        return "vcl"
    if nal_type in {32, 33, 34}:
        return "parameter_set"
    if nal_type in {39, 40}:
        return "sei"
    return "non_vcl"


def scan_hevc_access_units(path: str | Path) -> dict[str, Any]:
    """Scan every sample and NAL boundary while reading only length/header bytes."""

    source = Path(path).resolve()
    layout = primary_hevc_sample_layout(source)
    width = layout["nal_length_bytes"]
    if width not in {1, 2, 4}:
        raise HEVCGOPError("unsupported HEVC NAL length width")
    access_units: list[dict[str, Any]] = []
    type_counts: Counter[int] = Counter()
    physical_header_bytes_read = 0
    with source.open("rb", buffering=1024 * 1024) as stream:
        for sample in layout["samples"]:
            sample_offset = int(sample["offset"])
            sample_bytes = int(sample["bytes"])
            cursor = sample_offset
            boundary = sample_offset + sample_bytes
            nals: list[dict[str, Any]] = []
            while cursor < boundary:
                if boundary - cursor < width:
                    raise HEVCGOPError(
                        f"sample {sample['sample_index']} has a truncated NAL length"
                    )
                prefix = _read_exact(stream, cursor, width)
                physical_header_bytes_read += width
                nal_bytes = int.from_bytes(prefix, "big")
                prefix_offset = cursor
                cursor += width
                if nal_bytes < 2 or cursor + nal_bytes > boundary:
                    raise HEVCGOPError(
                        f"sample {sample['sample_index']} contains an invalid NAL range"
                    )
                header = _read_exact(stream, cursor, 2)
                physical_header_bytes_read += 2
                if header[0] & 0x80:
                    raise HEVCGOPError("HEVC forbidden_zero_bit is set")
                nal_type = (header[0] >> 1) & 0x3F
                layer_id = ((header[0] & 0x01) << 5) | (header[1] >> 3)
                temporal_id_plus1 = header[1] & 0x07
                if temporal_id_plus1 == 0:
                    raise HEVCGOPError("HEVC temporal_id_plus1 cannot be zero")
                nals.append(
                    {
                        "nal_index": len(nals),
                        "prefix_offset": prefix_offset,
                        "length_prefix_hex": prefix.hex(),
                        "nal_bytes": nal_bytes,
                        "header_offset": cursor,
                        "header_hex": header.hex(),
                        "body_offset": cursor + 2,
                        "body_bytes": nal_bytes - 2,
                        "nal_unit_type": nal_type,
                        "nal_class": _nal_class(nal_type),
                        "layer_id": layer_id,
                        "temporal_id_plus1": temporal_id_plus1,
                    }
                )
                type_counts[nal_type] += 1
                cursor += nal_bytes
            if cursor != boundary:
                raise HEVCGOPError("NAL units do not exactly cover their access unit")
            is_irap = any(16 <= item["nal_unit_type"] <= 23 for item in nals)
            access_units.append(
                {
                    "sample_index": int(sample["sample_index"]),
                    "offset": sample_offset,
                    "bytes": sample_bytes,
                    "nal_count": len(nals),
                    "is_irap": is_irap,
                    "nal_units": nals,
                }
            )

    gops: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for unit in access_units:
        if current is None or unit["is_irap"]:
            current = {
                "gop_index": len(gops),
                "first_sample_index": unit["sample_index"],
                "sample_indices": [],
                "starts_with_irap": bool(unit["is_irap"]),
            }
            gops.append(current)
        current["sample_indices"].append(unit["sample_index"])
        current["last_sample_index"] = unit["sample_index"]
        current["sample_count"] = len(current["sample_indices"])
        current["bytes"] = current.get("bytes", 0) + unit["bytes"]

    sample_sizes = sorted(unit["bytes"] for unit in access_units)
    if not sample_sizes:
        raise HEVCGOPError("HEVC layout contains no access units")
    return {
        "schema": "casulo.hevc-access-unit-map/1.0",
        "source": layout["source"],
        "sample_count": len(access_units),
        "sample_payload_bytes": sum(unit["bytes"] for unit in access_units),
        "sample_size_bytes": {
            "minimum": sample_sizes[0],
            "median": sample_sizes[len(sample_sizes) // 2],
            "maximum": sample_sizes[-1],
        },
        "nal_length_bytes": width,
        "nal_unit_count": sum(unit["nal_count"] for unit in access_units),
        "nal_unit_type_counts": {
            str(key): value for key, value in sorted(type_counts.items())
        },
        "physical_header_bytes_read": physical_header_bytes_read,
        "access_units": access_units,
        "gops": gops,
        "gop_count": len(gops),
        "read_policy": "all NAL length fields and two-byte headers; entropy-coded bodies skipped",
    }


def choose_irap_aligned_probe(
    analysis: dict[str, Any],
    *,
    target_bytes: int,
    minimum_samples: int = 2,
) -> tuple[int, ...]:
    if target_bytes <= 0 or minimum_samples < 1:
        raise ValueError("probe limits must be positive")
    units = analysis.get("access_units")
    if not isinstance(units, list) or not units:
        raise HEVCGOPError("access-unit analysis is empty")
    for start, unit in enumerate(units):
        if not unit.get("is_irap"):
            continue
        selected: list[int] = []
        total = 0
        for candidate in units[start:]:
            size = int(candidate["bytes"])
            if selected and total + size > target_bytes:
                break
            if not selected and size > target_bytes:
                break
            selected.append(int(candidate["sample_index"]))
            total += size
        if len(selected) >= minimum_samples:
            return tuple(selected)
    raise HEVCGOPError(
        "no IRAP-aligned sample sequence fits the probe budget and minimum sample count"
    )


def build_sample_aligned_corpus(
    source: str | Path,
    destination: str | Path,
    analysis: dict[str, Any],
    sample_indices: Sequence[int],
) -> dict[str, Any]:
    """Copy complete access units to a bounded corpus and seal all boundaries."""

    src = Path(source).resolve()
    dst = Path(destination).resolve()
    if dst.exists():
        raise FileExistsError(dst)
    if not sample_indices or tuple(sample_indices) != tuple(
        range(sample_indices[0], sample_indices[0] + len(sample_indices))
    ):
        raise HEVCGOPError("probe samples must be a non-empty contiguous sequence")
    by_index = {int(item["sample_index"]): item for item in analysis["access_units"]}
    if any(index not in by_index for index in sample_indices):
        raise HEVCGOPError("probe references an unknown sample")
    if not by_index[sample_indices[0]]["is_irap"]:
        raise HEVCGOPError("probe must start at an IRAP access unit")
    final_sample_index = sample_indices[-1]
    next_unit = by_index.get(final_sample_index + 1)
    complete_gop = next_unit is None or bool(next_unit["is_irap"])

    dst.parent.mkdir(parents=True, exist_ok=True)
    corpus_hash = hashlib.sha256()
    selected_rows: list[dict[str, Any]] = []
    corpus_offset = 0
    with src.open("rb", buffering=4 * 1024 * 1024) as reader, dst.open(
        "xb", buffering=4 * 1024 * 1024
    ) as writer:
        for index in sample_indices:
            unit = by_index[index]
            remaining = int(unit["bytes"])
            reader.seek(int(unit["offset"]))
            sample_hash = hashlib.sha256()
            while remaining:
                block = reader.read(min(4 * 1024 * 1024, remaining))
                if not block:
                    raise HEVCGOPError("source ended while constructing sample corpus")
                writer.write(block)
                sample_hash.update(block)
                corpus_hash.update(block)
                remaining -= len(block)
            nals = []
            for nal in unit["nal_units"]:
                relative_prefix = int(nal["prefix_offset"]) - int(unit["offset"])
                nals.append(
                    {
                        **nal,
                        "source_prefix_offset": nal["prefix_offset"],
                        "corpus_prefix_offset": corpus_offset + relative_prefix,
                        "corpus_body_offset": corpus_offset
                        + int(nal["body_offset"])
                        - int(unit["offset"]),
                    }
                )
            selected_rows.append(
                {
                    "sample_index": index,
                    "source_offset": int(unit["offset"]),
                    "corpus_offset": corpus_offset,
                    "bytes": int(unit["bytes"]),
                    "sha256": sample_hash.hexdigest(),
                    "is_irap": bool(unit["is_irap"]),
                    "nal_units": nals,
                }
            )
            corpus_offset += int(unit["bytes"])
        writer.flush()
        os.fsync(writer.fileno())
    return {
        "schema": "casulo.hevc-sample-corpus/1.0",
        "source": {"path": str(src), "bytes": src.stat().st_size},
        "corpus": {
            "path": str(dst),
            "bytes": corpus_offset,
            "sha256": corpus_hash.hexdigest(),
        },
        "nal_length_bytes": int(analysis["nal_length_bytes"]),
        "nal_unit_count": sum(len(row["nal_units"]) for row in selected_rows),
        "sample_indices": list(sample_indices),
        "samples": selected_rows,
        "sample_aligned": True,
        "starts_with_irap": True,
        "complete_gop": complete_gop,
        "scientific_eligible": False,
        "purpose": "bounded execution probe of HEVC access-unit/GOP transforms",
    }


__all__ = [
    "HEVCGOPError",
    "build_sample_aligned_corpus",
    "choose_irap_aligned_probe",
    "scan_hevc_access_units",
]
