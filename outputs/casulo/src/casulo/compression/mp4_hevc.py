from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable


class MP4AnalysisError(ValueError):
    """The byte stream is not a structurally safe ISO BMFF input."""


CONTAINER_TYPES = frozenset(
    {
        "moov",
        "trak",
        "mdia",
        "minf",
        "stbl",
        "edts",
        "dinf",
        "udta",
        "ilst",
        "moof",
        "traf",
        "mvex",
        "mfra",
        "wave",
    }
)
FULLBOX_CONTAINERS = {"meta": 4, "dref": 8, "stsd": 8}
SAMPLE_ENTRY_PREFIX = {"hvc1": 78, "hev1": 78, "avc1": 78, "avc3": 78, "mp4a": 28}
HEVC_SAMPLE_ENTRIES = frozenset({"hvc1", "hev1"})


@dataclass(frozen=True, slots=True)
class MP4Box:
    index: int
    type: str
    offset: int
    size: int
    header_bytes: int
    payload_offset: int
    payload_bytes: int
    depth: int
    parent_index: int | None

    @property
    def end(self) -> int:
        return self.offset + self.size

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "type": self.type,
            "offset": self.offset,
            "size": self.size,
            "header_bytes": self.header_bytes,
            "payload_offset": self.payload_offset,
            "payload_bytes": self.payload_bytes,
            "depth": self.depth,
            "parent_index": self.parent_index,
        }


def _box_header(stream: BinaryIO, offset: int, boundary: int) -> tuple[str, int, int]:
    if boundary - offset < 8:
        raise MP4AnalysisError(f"trailing bytes without MP4 header at {offset}")
    stream.seek(offset)
    raw = stream.read(8)
    if len(raw) != 8:
        raise MP4AnalysisError(f"truncated MP4 header at {offset}")
    size32, raw_type = struct.unpack(">I4s", raw)
    box_type = raw_type.decode("latin-1")
    header = 8
    if size32 == 1:
        extended = stream.read(8)
        if len(extended) != 8:
            raise MP4AnalysisError(f"truncated extended MP4 header at {offset}")
        size = struct.unpack(">Q", extended)[0]
        header = 16
    elif size32 == 0:
        size = boundary - offset
    else:
        size = size32
    if box_type == "uuid":
        user_type = stream.read(16)
        if len(user_type) != 16:
            raise MP4AnalysisError(f"truncated uuid MP4 header at {offset}")
        header += 16
    if size < header:
        raise MP4AnalysisError(f"MP4 box {box_type!r} smaller than its header at {offset}")
    if offset + size > boundary:
        raise MP4AnalysisError(f"MP4 box {box_type!r} exceeds parent boundary at {offset}")
    return box_type, size, header


def _child_start(box: MP4Box) -> int | None:
    if box.type in CONTAINER_TYPES:
        return box.payload_offset
    if box.type in FULLBOX_CONTAINERS:
        return box.payload_offset + FULLBOX_CONTAINERS[box.type]
    if box.type in SAMPLE_ENTRY_PREFIX:
        return box.payload_offset + SAMPLE_ENTRY_PREFIX[box.type]
    return None


def parse_boxes(path: str | Path, *, max_boxes: int = 100_000, max_depth: int = 24) -> tuple[MP4Box, ...]:
    source = Path(path).resolve()
    size = source.stat().st_size
    if size < 8:
        raise MP4AnalysisError("input shorter than one MP4 box")
    boxes: list[MP4Box] = []
    with source.open("rb", buffering=1024 * 1024) as stream:
        stack: list[tuple[int, int, int, int | None]] = [(0, size, 0, None)]
        while stack:
            start, boundary, depth, parent = stack.pop()
            if depth > max_depth:
                raise MP4AnalysisError("MP4 nesting depth exceeds safety budget")
            offset = start
            children: list[MP4Box] = []
            while offset < boundary:
                if len(boxes) >= max_boxes:
                    raise MP4AnalysisError("MP4 box count exceeds safety budget")
                box_type, box_size, header = _box_header(stream, offset, boundary)
                box = MP4Box(
                    index=len(boxes),
                    type=box_type,
                    offset=offset,
                    size=box_size,
                    header_bytes=header,
                    payload_offset=offset + header,
                    payload_bytes=box_size - header,
                    depth=depth,
                    parent_index=parent,
                )
                boxes.append(box)
                children.append(box)
                offset += box_size
            if offset != boundary:
                raise MP4AnalysisError("MP4 sibling boxes do not exactly cover their boundary")
            # Reverse insertion preserves file order when the stack pops.
            for box in reversed(children):
                nested = _child_start(box)
                if nested is None or nested == box.end:
                    continue
                if nested > box.end:
                    raise MP4AnalysisError(f"container prefix exceeds {box.type} at {box.offset}")
                stack.append((nested, box.end, depth + 1, box.index))
    return tuple(sorted(boxes, key=lambda item: (item.offset, item.depth)))


def _read_exact(stream: BinaryIO, offset: int, length: int) -> bytes:
    stream.seek(offset)
    value = stream.read(length)
    if len(value) != length:
        raise MP4AnalysisError(f"truncated read at {offset} ({length} bytes)")
    return value


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for value in data:
        counts[value] += 1
    length = len(data)
    return -sum((count / length) * math.log2(count / length) for count in counts if count)


def _sample_payload(stream: BinaryIO, box: MP4Box, *, sample_bytes: int = 65_536) -> bytes:
    if box.payload_bytes <= sample_bytes * 3:
        return _read_exact(stream, box.payload_offset, box.payload_bytes)
    offsets = (
        box.payload_offset,
        box.payload_offset + (box.payload_bytes - sample_bytes) // 2,
        box.end - sample_bytes,
    )
    return b"".join(_read_exact(stream, offset, sample_bytes) for offset in offsets)


def _parse_hvcc(data: bytes) -> dict[str, Any]:
    if len(data) < 23 or data[0] != 1:
        raise MP4AnalysisError("invalid hvcC configuration record")
    cursor = 23
    arrays: list[dict[str, int]] = []
    counts = {"vps": 0, "sps": 0, "pps": 0}
    for _ in range(data[22]):
        if cursor + 3 > len(data):
            raise MP4AnalysisError("truncated hvcC array")
        nal_type = data[cursor] & 0x3F
        units = struct.unpack(">H", data[cursor + 1 : cursor + 3])[0]
        cursor += 3
        payload_bytes = 0
        for _unit in range(units):
            if cursor + 2 > len(data):
                raise MP4AnalysisError("truncated hvcC NAL length")
            unit_bytes = struct.unpack(">H", data[cursor : cursor + 2])[0]
            cursor += 2
            if cursor + unit_bytes > len(data):
                raise MP4AnalysisError("truncated hvcC NAL unit")
            cursor += unit_bytes
            payload_bytes += unit_bytes
        arrays.append({"nal_unit_type": nal_type, "units": units, "payload_bytes": payload_bytes})
        if nal_type == 32:
            counts["vps"] += units
        elif nal_type == 33:
            counts["sps"] += units
        elif nal_type == 34:
            counts["pps"] += units
    return {
        "configuration_version": data[0],
        "general_profile_idc": data[1] & 0x1F,
        "general_level_idc": data[12],
        "nal_length_bytes": (data[21] & 0x03) + 1,
        "array_count": data[22],
        "vps_count": counts["vps"],
        "sps_count": counts["sps"],
        "pps_count": counts["pps"],
        "arrays": arrays,
        "trailing_bytes": len(data) - cursor,
    }


def _parse_fixed_table(stream: BinaryIO, box: MP4Box) -> dict[str, Any] | None:
    if box.type == "stsz" and box.payload_bytes >= 12:
        header = _read_exact(stream, box.payload_offset, 12)
        sample_size, sample_count = struct.unpack(">II", header[4:12])
        return {"type": "stsz", "sample_size": sample_size, "sample_count": sample_count}
    if box.type in {"stco", "co64"} and box.payload_bytes >= 8:
        header = _read_exact(stream, box.payload_offset, 8)
        return {"type": box.type, "entry_count": struct.unpack(">I", header[4:8])[0]}
    if box.type == "stsc" and box.payload_bytes >= 8:
        header = _read_exact(stream, box.payload_offset, 8)
        return {"type": "stsc", "entry_count": struct.unpack(">I", header[4:8])[0]}
    return None


def _read_uint_table(
    stream: BinaryIO,
    *,
    offset: int,
    count: int,
    width: int,
    boundary: int,
) -> list[int]:
    if count < 0 or count > 1_000_000 or width not in {4, 8}:
        raise MP4AnalysisError("sample table exceeds defensive budget")
    byte_count = count * width
    if offset + byte_count > boundary:
        raise MP4AnalysisError("sample table exceeds box boundary")
    data = _read_exact(stream, offset, byte_count)
    code = ">I" if width == 4 else ">Q"
    return [struct.unpack(code, data[index : index + width])[0] for index in range(0, byte_count, width)]


def _detailed_sample_table(stream: BinaryIO, box: MP4Box) -> dict[str, Any] | None:
    if box.type == "stsz" and box.payload_bytes >= 12:
        header = _read_exact(stream, box.payload_offset, 12)
        sample_size, count = struct.unpack(">II", header[4:12])
        sizes = [sample_size] * count if sample_size else _read_uint_table(
            stream,
            offset=box.payload_offset + 12,
            count=count,
            width=4,
            boundary=box.end,
        )
        return {"type": "stsz", "sample_count": count, "sample_size": sample_size, "sizes": sizes}
    if box.type in {"stco", "co64"} and box.payload_bytes >= 8:
        count = struct.unpack(">I", _read_exact(stream, box.payload_offset + 4, 4))[0]
        return {
            "type": box.type,
            "entry_count": count,
            "offsets": _read_uint_table(
                stream,
                offset=box.payload_offset + 8,
                count=count,
                width=4 if box.type == "stco" else 8,
                boundary=box.end,
            ),
        }
    if box.type == "stsc" and box.payload_bytes >= 8:
        count = struct.unpack(">I", _read_exact(stream, box.payload_offset + 4, 4))[0]
        if count > 1_000_000 or box.payload_offset + 8 + count * 12 > box.end:
            raise MP4AnalysisError("stsc exceeds defensive size or box boundary")
        raw = _read_exact(stream, box.payload_offset + 8, count * 12)
        entries = [
            {
                "first_chunk": struct.unpack(">I", raw[index : index + 4])[0],
                "samples_per_chunk": struct.unpack(">I", raw[index + 4 : index + 8])[0],
                "sample_description_index": struct.unpack(">I", raw[index + 8 : index + 12])[0],
            }
            for index in range(0, len(raw), 12)
        ]
        if not entries or entries[0]["first_chunk"] != 1 or any(
            left["first_chunk"] >= right["first_chunk"] for left, right in zip(entries, entries[1:])
        ):
            raise MP4AnalysisError("invalid stsc ordering")
        return {"type": "stsc", "entry_count": count, "entries": entries}
    return None


def _sample_layout(tables: dict[str, dict[str, Any]], source_bytes: int) -> list[tuple[int, int]]:
    stsz = tables.get("stsz")
    chunks = tables.get("co64") or tables.get("stco")
    stsc = tables.get("stsc")
    if stsz is None or chunks is None or stsc is None:
        return []
    sizes = stsz["sizes"]
    chunk_offsets = chunks["offsets"]
    entries = stsc["entries"]
    samples: list[tuple[int, int]] = []
    size_index = 0
    entry_index = 0
    for chunk_number, chunk_offset in enumerate(chunk_offsets, 1):
        while entry_index + 1 < len(entries) and entries[entry_index + 1]["first_chunk"] <= chunk_number:
            entry_index += 1
        within = 0
        for _ in range(entries[entry_index]["samples_per_chunk"]):
            if size_index >= len(sizes):
                raise MP4AnalysisError("stsc references more samples than stsz")
            sample_size = sizes[size_index]
            sample_offset = chunk_offset + within
            if sample_offset + sample_size > source_bytes:
                raise MP4AnalysisError("sample range exceeds source")
            samples.append((sample_offset, sample_size))
            within += sample_size
            size_index += 1
    if size_index != len(sizes):
        raise MP4AnalysisError("sample tables leave stsz entries unmapped")
    return samples


def _probe_indices(count: int, limit: int = 64) -> list[int]:
    if count <= limit:
        return list(range(count))
    points = {0, count - 1}
    for index in range(limit):
        points.add(round(index * (count - 1) / (limit - 1)))
    return sorted(points)


def _probe_hevc_samples(
    stream: BinaryIO,
    samples: list[tuple[int, int]],
    *,
    nal_length_bytes: int,
) -> dict[str, Any]:
    if nal_length_bytes not in {1, 2, 4}:
        raise MP4AnalysisError("unsupported HEVC NAL length width")
    nal_types: dict[int, int] = {}
    sample_rows: list[dict[str, Any]] = []
    physical_header_bytes_read = 0
    for sample_index in _probe_indices(len(samples)):
        sample_offset, sample_bytes = samples[sample_index]
        cursor = sample_offset
        boundary = sample_offset + sample_bytes
        types: list[int] = []
        while cursor < boundary:
            if boundary - cursor < nal_length_bytes:
                raise MP4AnalysisError("truncated HEVC NAL length in sample")
            length_raw = _read_exact(stream, cursor, nal_length_bytes)
            physical_header_bytes_read += nal_length_bytes
            nal_bytes = int.from_bytes(length_raw, "big")
            cursor += nal_length_bytes
            if nal_bytes <= 0 or cursor + nal_bytes > boundary:
                raise MP4AnalysisError("HEVC NAL range exceeds sample")
            header = _read_exact(stream, cursor, min(2, nal_bytes))
            physical_header_bytes_read += len(header)
            if len(header) < 2:
                raise MP4AnalysisError("HEVC NAL header is truncated")
            nal_type = (header[0] >> 1) & 0x3F
            types.append(nal_type)
            nal_types[nal_type] = nal_types.get(nal_type, 0) + 1
            cursor += nal_bytes
        sample_rows.append(
            {
                "sample_index": sample_index,
                "offset": sample_offset,
                "bytes": sample_bytes,
                "nal_unit_types": types,
                "is_irap": any(16 <= item <= 23 for item in types),
            }
        )
    return {
        "declared_samples": len(samples),
        "probed_samples": len(sample_rows),
        "probe_policy": "up to 64 uniformly spaced samples; NAL headers only",
        "physical_header_bytes_read": physical_header_bytes_read,
        "nal_unit_type_counts": {str(key): value for key, value in sorted(nal_types.items())},
        "irap_sample_indices": [row["sample_index"] for row in sample_rows if row["is_irap"]],
        "samples": sample_rows,
    }


def analyze_mp4_hevc(
    path: str | Path,
    *,
    strict_sample_layout: bool = True,
) -> dict[str, Any]:
    source = Path(path).resolve()
    source_bytes = source.stat().st_size
    boxes = parse_boxes(source)
    top = [box for box in boxes if box.depth == 0]
    top_cover = bool(top) and top[0].offset == 0 and top[-1].end == source_bytes and all(
        left.end == right.offset for left, right in zip(top, top[1:])
    )
    if not top_cover:
        raise MP4AnalysisError("top-level MP4 boxes do not cover the complete source")
    sample_entries = sorted({box.type for box in boxes if box.type in SAMPLE_ENTRY_PREFIX})
    hvcc_records: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    detailed_by_parent: dict[int, dict[str, dict[str, Any]]] = {}
    entropy_samples: list[dict[str, Any]] = []
    sample_probe: dict[str, Any] | None = None
    sample_layout_diagnostics: list[str] = []
    with source.open("rb", buffering=1024 * 1024) as stream:
        for box in boxes:
            if box.type == "hvcC":
                if box.payload_bytes > 4 * 1024 * 1024:
                    raise MP4AnalysisError("hvcC exceeds defensive size limit")
                hvcc_records.append({"box_index": box.index, **_parse_hvcc(_read_exact(stream, box.payload_offset, box.payload_bytes))})
            table = _parse_fixed_table(stream, box)
            if table is not None:
                tables.append({"box_index": box.index, **table})
            detailed = _detailed_sample_table(stream, box)
            if detailed is not None and box.parent_index is not None:
                detailed_by_parent.setdefault(box.parent_index, {})[box.type] = detailed
        for box in top:
            sampled = _sample_payload(stream, box)
            entropy_samples.append(
                {
                    "box_index": box.index,
                    "type": box.type,
                    "sample_bytes": len(sampled),
                    "shannon_bits_per_byte": round(_entropy(sampled), 9),
                }
            )
        if hvcc_records:
            layouts = []
            for group in detailed_by_parent.values():
                if not ({"stsz", "stsc"}.issubset(group) and ({"stco", "co64"} & set(group))):
                    continue
                try:
                    layouts.append(_sample_layout(group, source_bytes))
                except MP4AnalysisError as exc:
                    if strict_sample_layout:
                        raise
                    sample_layout_diagnostics.append(str(exc))
            layouts = [layout for layout in layouts if layout]
            if layouts:
                largest = max(layouts, key=len)
                sample_probe = _probe_hevc_samples(
                    stream,
                    largest,
                    nal_length_bytes=hvcc_records[0]["nal_length_bytes"],
                )
    return {
        "schema": "casulo.mp4-hevc-structure/1.0",
        "source": {"name": source.name, "bytes": source_bytes},
        "is_iso_bmff": any(box.type == "ftyp" for box in top),
        "top_level_exact_cover": top_cover,
        "top_level_boxes": [box.to_dict() for box in top],
        "all_boxes": [box.to_dict() for box in boxes],
        "box_count": len(boxes),
        "sample_entries": sample_entries,
        "is_hevc": bool(HEVC_SAMPLE_ENTRIES.intersection(sample_entries) or hvcc_records),
        "hevc_configuration_records": hvcc_records,
        "sample_tables": tables,
        "hevc_sample_probe": sample_probe,
        "sample_layout_valid": not sample_layout_diagnostics,
        "sample_layout_diagnostics": sample_layout_diagnostics,
        "entropy_samples": entropy_samples,
        "analysis_read_policy": "headers + bounded tables + <=3x64KiB per top-level payload",
    }


def primary_hevc_sample_layout(path: str | Path) -> dict[str, Any]:
    """Return the complete primary HEVC sample layout without reading frame bodies.

    The function reads MP4 box headers, the bounded ``hvcC`` record and sample
    tables.  The returned offsets are validated against the physical source.
    Callers can then seek directly to NAL length/header fields while leaving
    entropy-coded payloads untouched.
    """

    source = Path(path).resolve()
    source_bytes = source.stat().st_size
    boxes = parse_boxes(source)
    detailed_by_parent: dict[int, dict[str, dict[str, Any]]] = {}
    configurations: list[dict[str, Any]] = []
    with source.open("rb", buffering=1024 * 1024) as stream:
        for box in boxes:
            if box.type == "hvcC":
                if box.payload_bytes > 4 * 1024 * 1024:
                    raise MP4AnalysisError("hvcC exceeds defensive size limit")
                configurations.append(
                    {
                        "box_index": box.index,
                        **_parse_hvcc(
                            _read_exact(stream, box.payload_offset, box.payload_bytes)
                        ),
                    }
                )
            detailed = _detailed_sample_table(stream, box)
            if detailed is not None and box.parent_index is not None:
                detailed_by_parent.setdefault(box.parent_index, {})[box.type] = detailed
    if not configurations:
        raise MP4AnalysisError("HEVC configuration record not found")
    layouts: list[tuple[int, list[tuple[int, int]]]] = []
    for parent_index, group in detailed_by_parent.items():
        if not ({"stsz", "stsc"}.issubset(group) and ({"stco", "co64"} & set(group))):
            continue
        layout = _sample_layout(group, source_bytes)
        if layout:
            layouts.append((parent_index, layout))
    if not layouts:
        raise MP4AnalysisError("complete HEVC sample layout not found")
    parent_index, selected = max(layouts, key=lambda item: len(item[1]))
    return {
        "schema": "casulo.hevc-sample-layout/1.0",
        "source": {"name": source.name, "bytes": source_bytes},
        "sample_table_parent_index": parent_index,
        "nal_length_bytes": configurations[0]["nal_length_bytes"],
        "hevc_configuration": configurations[0],
        "sample_count": len(selected),
        "sample_payload_bytes": sum(size for _offset, size in selected),
        "samples": [
            {"sample_index": index, "offset": offset, "bytes": size}
            for index, (offset, size) in enumerate(selected)
        ],
        "read_policy": "MP4 headers + hvcC + sample tables; no frame body read",
    }


def build_bounded_mp4_probe(
    source: str | Path,
    destination: str | Path,
    *,
    media_payload_bytes: int = 4 * 1024 * 1024,
    metadata_limit_bytes: int = 16 * 1024 * 1024,
) -> dict[str, Any]:
    """Build a source-derived structural probe, never claimed to be playable.

    Small top-level metadata boxes are retained byte-for-byte. Each mdat keeps a
    bounded prefix and receives a new correct box length. Absolute sample-table
    offsets are deliberately not rewritten, so playability is not asserted.
    """

    if media_payload_bytes <= 0 or metadata_limit_bytes <= 0:
        raise ValueError("probe byte limits must be positive")
    src = Path(source).resolve()
    dst = Path(destination).resolve()
    if dst.exists():
        raise FileExistsError(dst)
    analysis = analyze_mp4_hevc(src)
    selected: list[dict[str, Any]] = []
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb", buffering=1024 * 1024) as reader, dst.open("xb", buffering=1024 * 1024) as writer:
        for raw_box in analysis["top_level_boxes"]:
            box_type = raw_box["type"]
            box_bytes = raw_box["size"]
            if box_type == "mdat":
                take = min(raw_box["payload_bytes"], media_payload_bytes)
                new_size = 8 + take
                if new_size > 0xFFFFFFFF:
                    header = struct.pack(">I4sQ", 1, b"mdat", 16 + take)
                else:
                    header = struct.pack(">I4s", new_size, b"mdat")
                writer.write(header)
                reader.seek(raw_box["payload_offset"])
                remaining = take
                while remaining:
                    block = reader.read(min(1024 * 1024, remaining))
                    if not block:
                        raise MP4AnalysisError("source ended while constructing probe")
                    writer.write(block)
                    remaining -= len(block)
                selected.append({"type": box_type, "source_offset": raw_box["offset"], "source_bytes": raw_box["size"], "probe_bytes": len(header) + take, "payload_truncated": take != raw_box["payload_bytes"]})
            elif box_bytes <= metadata_limit_bytes:
                reader.seek(raw_box["offset"])
                remaining = box_bytes
                while remaining:
                    block = reader.read(min(1024 * 1024, remaining))
                    if not block:
                        raise MP4AnalysisError("source ended while copying metadata")
                    writer.write(block)
                    remaining -= len(block)
                selected.append({"type": box_type, "source_offset": raw_box["offset"], "source_bytes": box_bytes, "probe_bytes": box_bytes, "payload_truncated": False})
            else:
                selected.append({"type": box_type, "source_offset": raw_box["offset"], "source_bytes": box_bytes, "probe_bytes": 0, "omitted_by_probe_budget": True})
        writer.flush()
        os.fsync(writer.fileno())
    return {
        "schema": "casulo.source-derived-mp4-probe/1.0",
        "source": {"path": str(src), "bytes": src.stat().st_size},
        "probe": {"path": str(dst), "bytes": dst.stat().st_size},
        "selected_top_level_boxes": selected,
        "scientific_eligible": False,
        "playable_not_claimed": True,
        "purpose": "short execution proof of structural path and exact reconstruction",
    }


def top_level_boxes(analysis: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return tuple(analysis["top_level_boxes"])
