from __future__ import annotations

import struct
import zlib
from collections import Counter
from dataclasses import dataclass
from typing import Iterator

from .casv_ir import CanonicalVideoSpec, RectTrack


SEGMENT_BASE_MAGIC = b"CVB3"
SEGMENT_DYNAMICS_MAGIC = b"CVD3"
SEGMENT_PROGRAM_MAGIC = b"CVG3"
SEGMENT_RENDERER = "casulo.rectilinear-rgb8-yuv444p10le/0.3"
MAX_PROPOSER_PIXELS = 1_000_000
MAX_TRACKS = 32
MAX_MATERIAL_CANDIDATES = 64

PIXEL_FORMAT_IDS = {"RGB8": 1, "YUV444P10LE": 2}
_BASE_HEADER = struct.Struct(">4sIIIIIIIII")
_MATERIAL = struct.Struct(">HHH")
_BASE_TRACK = struct.Struct(">iiIIII")
_DYNAMICS_HEADER = struct.Struct(">4sI")
_DYNAMICS_TRACK = struct.Struct(">ii")
_PROGRAM_HEADER = struct.Struct(">4sIIII")


class CASVSegmentIRError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SegmentMaterial:
    channel_0: int
    channel_1: int
    channel_2: int

    def values(self) -> tuple[int, int, int]:
        return self.channel_0, self.channel_1, self.channel_2


@dataclass(frozen=True, slots=True)
class CausalSegmentProgram:
    spec: CanonicalVideoSpec
    materials: tuple[SegmentMaterial, ...]
    background_material_index: int
    tracks: tuple[RectTrack, ...]

    def validate(self) -> None:
        self.spec.validate(enforce_memory_limit=False)
        if self.spec.pixel_format not in PIXEL_FORMAT_IDS:
            raise CASVSegmentIRError("segment renderer pixel format is unsupported")
        if not self.materials:
            raise CASVSegmentIRError("segment renderer needs at least one material")
        maximum = 255 if self.spec.pixel_format == "RGB8" else 1023
        for material in self.materials:
            if any(not 0 <= value <= maximum for value in material.values()):
                raise CASVSegmentIRError("segment material channel is outside bounds")
        if not 0 <= self.background_material_index < len(self.materials):
            raise CASVSegmentIRError("segment background material is unknown")
        if len(self.tracks) > MAX_TRACKS:
            raise CASVSegmentIRError("segment track count exceeds proposer bounds")
        seen_z: set[int] = set()
        for track in self.tracks:
            track.validate(self.spec, len(self.materials))
            if track.z_index in seen_z:
                raise CASVSegmentIRError("segment track z-index values must be unique")
            seen_z.add(track.z_index)


@dataclass(frozen=True, slots=True)
class SegmentSceneInference:
    program: CausalSegmentProgram
    rendered: bytes
    residual_xor: bytes
    residual_payload: bytes
    residual_encoding: str
    residual_nonzero_bytes: int
    exact_predicted_pixels: int
    detected_tracks: int

    @property
    def total_pixels(self) -> int:
        spec = self.program.spec
        return spec.width * spec.height * spec.frame_count


def _iter_pixels(frame: memoryview, spec: CanonicalVideoSpec) -> Iterator[tuple[int, int, int]]:
    pixels = spec.width * spec.height
    if spec.pixel_format == "RGB8":
        for index in range(pixels):
            offset = index * 3
            yield frame[offset], frame[offset + 1], frame[offset + 2]
        return
    plane_bytes = pixels * 2
    for index in range(pixels):
        offset = index * 2
        yield (
            struct.unpack_from("<H", frame, offset)[0],
            struct.unpack_from("<H", frame, plane_bytes + offset)[0],
            struct.unpack_from("<H", frame, 2 * plane_bytes + offset)[0],
        )


def _rectangle_for_color(
    frame: memoryview,
    spec: CanonicalVideoSpec,
    color: tuple[int, int, int],
) -> tuple[int, int, int, int] | None:
    count = 0
    min_x = spec.width
    min_y = spec.height
    max_x = -1
    max_y = -1
    for index, pixel in enumerate(_iter_pixels(frame, spec)):
        if pixel != color:
            continue
        x = index % spec.width
        y = index // spec.width
        count += 1
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)
    if count < 4:
        return None
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    if count != width * height:
        return None
    return min_x, min_y, width, height


def _render_rgb8(program: CausalSegmentProgram) -> bytes:
    spec = program.spec
    background = bytes(program.materials[program.background_material_index].values())
    output = bytearray()
    tracks = sorted(program.tracks, key=lambda item: item.z_index)
    for frame_index in range(spec.frame_count):
        frame = bytearray(background * (spec.width * spec.height))
        for track in tracks:
            color = bytes(program.materials[track.material_index].values())
            x = track.x0 + frame_index * track.dx_per_frame
            y = track.y0 + frame_index * track.dy_per_frame
            row = color * track.width
            for offset_y in range(track.height):
                start = ((y + offset_y) * spec.width + x) * 3
                frame[start : start + len(row)] = row
        output.extend(frame)
    return bytes(output)


def _render_yuv444p10le(program: CausalSegmentProgram) -> bytes:
    spec = program.spec
    pixels = spec.width * spec.height
    background = program.materials[program.background_material_index].values()
    tracks = sorted(program.tracks, key=lambda item: item.z_index)
    output = bytearray()
    for frame_index in range(spec.frame_count):
        planes = [bytearray(value.to_bytes(2, "little") * pixels) for value in background]
        for track in tracks:
            values = program.materials[track.material_index].values()
            x = track.x0 + frame_index * track.dx_per_frame
            y = track.y0 + frame_index * track.dy_per_frame
            for plane, value in zip(planes, values, strict=True):
                row = value.to_bytes(2, "little") * track.width
                for offset_y in range(track.height):
                    start = ((y + offset_y) * spec.width + x) * 2
                    plane[start : start + len(row)] = row
        output.extend(b"".join(planes))
    return bytes(output)


def render_segment_program(program: CausalSegmentProgram) -> bytes:
    program.validate()
    if program.spec.pixel_format == "RGB8":
        return _render_rgb8(program)
    return _render_yuv444p10le(program)


def infer_segment_program(payload: bytes, spec: CanonicalVideoSpec) -> SegmentSceneInference:
    spec.validate(enforce_memory_limit=False)
    if len(payload) != spec.expected_bytes:
        raise CASVSegmentIRError("segment payload differs from its canonical spec")
    total_pixels = spec.width * spec.height * spec.frame_count
    if total_pixels > MAX_PROPOSER_PIXELS:
        raise CASVSegmentIRError("segment exceeds bounded visual proposer")
    frames = [
        memoryview(payload)[index * spec.frame_bytes : (index + 1) * spec.frame_bytes]
        for index in range(spec.frame_count)
    ]
    first_counts = Counter(_iter_pixels(frames[0], spec))
    background = first_counts.most_common(1)[0][0]
    candidates = [
        color
        for color, count in first_counts.most_common(MAX_MATERIAL_CANDIDATES + 1)
        if color != background and count >= 4
    ][:MAX_MATERIAL_CANDIDATES]

    tracks_with_color: list[tuple[tuple[int, int, int], RectTrack]] = []
    for color in candidates:
        rectangles = [_rectangle_for_color(frame, spec, color) for frame in frames]
        if any(rectangle is None for rectangle in rectangles):
            continue
        resolved = [rectangle for rectangle in rectangles if rectangle is not None]
        x0, y0, width, height = resolved[0]
        if any(item[2:] != (width, height) for item in resolved):
            continue
        dx = resolved[1][0] - x0 if len(resolved) > 1 else 0
        dy = resolved[1][1] - y0 if len(resolved) > 1 else 0
        if any(
            (item[0], item[1]) != (x0 + index * dx, y0 + index * dy)
            for index, item in enumerate(resolved)
        ):
            continue
        tracks_with_color.append(
            (
                color,
                RectTrack(
                    x0=x0,
                    y0=y0,
                    width=width,
                    height=height,
                    dx_per_frame=dx,
                    dy_per_frame=dy,
                    material_index=len(tracks_with_color) + 1,
                    z_index=len(tracks_with_color),
                ),
            )
        )
        if len(tracks_with_color) == MAX_TRACKS:
            break

    program = CausalSegmentProgram(
        spec=spec,
        materials=(SegmentMaterial(*background),)
        + tuple(SegmentMaterial(*color) for color, _track in tracks_with_color),
        background_material_index=0,
        tracks=tuple(track for _color, track in tracks_with_color),
    )
    rendered = render_segment_program(program)
    residual = bytes(
        source ^ predicted for source, predicted in zip(payload, rendered, strict=True)
    )
    residual_nonzero = sum(value != 0 for value in residual)
    residual_encoding = "ZERO" if residual_nonzero == 0 else "XOR_ZLIB"
    residual_payload = b"" if residual_nonzero == 0 else zlib.compress(residual, level=9)
    rendered_frames = [
        memoryview(rendered)[index * spec.frame_bytes : (index + 1) * spec.frame_bytes]
        for index in range(spec.frame_count)
    ]
    exact_pixels = sum(
        left == right
        for source_frame, rendered_frame in zip(frames, rendered_frames, strict=True)
        for left, right in zip(
            _iter_pixels(source_frame, spec),
            _iter_pixels(rendered_frame, spec),
            strict=True,
        )
    )
    return SegmentSceneInference(
        program=program,
        rendered=rendered,
        residual_xor=residual,
        residual_payload=residual_payload,
        residual_encoding=residual_encoding,
        residual_nonzero_bytes=residual_nonzero,
        exact_predicted_pixels=exact_pixels,
        detected_tracks=len(program.tracks),
    )


def encode_segment_base(program: CausalSegmentProgram) -> bytes:
    program.validate()
    spec = program.spec
    payload = bytearray(
        _BASE_HEADER.pack(
            SEGMENT_BASE_MAGIC,
            PIXEL_FORMAT_IDS[spec.pixel_format],
            spec.width,
            spec.height,
            spec.frame_count,
            spec.fps_numerator,
            spec.fps_denominator,
            program.background_material_index,
            len(program.materials),
            len(program.tracks),
        )
    )
    for material in program.materials:
        payload.extend(_MATERIAL.pack(*material.values()))
    for track in sorted(program.tracks, key=lambda item: item.z_index):
        payload.extend(
            _BASE_TRACK.pack(
                track.x0,
                track.y0,
                track.width,
                track.height,
                track.material_index,
                track.z_index,
            )
        )
    return bytes(payload)


def encode_segment_dynamics(program: CausalSegmentProgram) -> bytes:
    program.validate()
    tracks = sorted(program.tracks, key=lambda item: item.z_index)
    payload = bytearray(_DYNAMICS_HEADER.pack(SEGMENT_DYNAMICS_MAGIC, len(tracks)))
    for track in tracks:
        payload.extend(_DYNAMICS_TRACK.pack(track.dx_per_frame, track.dy_per_frame))
    return bytes(payload)


def encode_segment_candidate(
    inference: SegmentSceneInference,
) -> tuple[bytes, dict[str, object]]:
    base = encode_segment_base(inference.program)
    dynamics = encode_segment_dynamics(inference.program)
    residual_mode = 0 if inference.residual_encoding == "ZERO" else 1
    residual = inference.residual_payload
    payload = (
        _PROGRAM_HEADER.pack(
            SEGMENT_PROGRAM_MAGIC,
            len(base),
            len(dynamics),
            residual_mode,
            len(residual),
        )
        + base
        + dynamics
        + residual
    )
    metadata: dict[str, object] = {
        "renderer": SEGMENT_RENDERER,
        "base_bytes": len(base),
        "dynamics_bytes": len(dynamics),
        "residual_encoding": inference.residual_encoding,
        "residual_logical_bytes": len(inference.residual_xor),
        "residual_stored_bytes": len(residual),
        "residual_nonzero_bytes": inference.residual_nonzero_bytes,
        "detected_tracks": inference.detected_tracks,
        "exact_predicted_pixels": inference.exact_predicted_pixels,
        "total_pixels": inference.total_pixels,
    }
    return payload, metadata


__all__ = [
    "CASVSegmentIRError",
    "CausalSegmentProgram",
    "MAX_PROPOSER_PIXELS",
    "PIXEL_FORMAT_IDS",
    "SEGMENT_BASE_MAGIC",
    "SEGMENT_DYNAMICS_MAGIC",
    "SEGMENT_PROGRAM_MAGIC",
    "SEGMENT_RENDERER",
    "SegmentMaterial",
    "SegmentSceneInference",
    "encode_segment_base",
    "encode_segment_candidate",
    "encode_segment_dynamics",
    "infer_segment_program",
    "render_segment_program",
]
