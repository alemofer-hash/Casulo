from __future__ import annotations

import hashlib
import struct
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


CASV_EQUIVALENCE = "EXACT_MEDIA"
CASV_PIXEL_FORMAT = "RGB8"
CASV_PIXEL_FORMAT_BYTES = {
    "RGB8": 3,
    "YUV444P10LE": 6,
}
CASV_RENDERER = "casulo.rectilinear-rgb8/0.1"
BASE_MAGIC = b"CVB1"
DYNAMICS_MAGIC = b"CVD1"
MAX_IN_MEMORY_BYTES = 256 * 1024 * 1024

_BASE_HEADER = struct.Struct(">4sIIIIIIIII")
_MATERIAL = struct.Struct(">BBBB")
_BASE_TRACK = struct.Struct(">iiIIII")
_DYNAMICS_HEADER = struct.Struct(">4sI")
_DYNAMICS_TRACK = struct.Struct(">ii")


class CASVIRError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalVideoSpec:
    width: int
    height: int
    frame_count: int
    fps_numerator: int
    fps_denominator: int = 1
    pixel_format: str = CASV_PIXEL_FORMAT

    def validate(self, *, enforce_memory_limit: bool = True) -> None:
        if self.pixel_format not in CASV_PIXEL_FORMAT_BYTES:
            raise CASVIRError("CASV/0.1 canonical pixel format is unsupported")
        if not 1 <= self.width <= 16_384 or not 1 <= self.height <= 16_384:
            raise CASVIRError("video dimensions are outside the CASV/0.1 bounds")
        if not 1 <= self.frame_count <= 1_000_000:
            raise CASVIRError("frame count is outside the CASV/0.1 bounds")
        if self.fps_numerator <= 0 or self.fps_denominator <= 0:
            raise CASVIRError("frame rate must be positive")
        if enforce_memory_limit and self.expected_bytes > MAX_IN_MEMORY_BYTES:
            raise CASVIRError(
                "CASV/0.1 is an in-memory bounded probe; streaming media is not implemented"
            )

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * CASV_PIXEL_FORMAT_BYTES[self.pixel_format]

    @property
    def expected_bytes(self) -> int:
        return self.frame_bytes * self.frame_count

    def as_dict(self) -> dict[str, int | str]:
        return {
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "fps_numerator": self.fps_numerator,
            "fps_denominator": self.fps_denominator,
            "pixel_format": self.pixel_format,
            "canonical_bytes": self.expected_bytes,
        }


@dataclass(frozen=True, slots=True)
class Material:
    red: int
    green: int
    blue: int
    brightness_q8: int = 255

    def validate(self) -> None:
        if any(not 0 <= value <= 255 for value in self.as_tuple()):
            raise CASVIRError("material channels and brightness must fit in one byte")

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.red, self.green, self.blue, self.brightness_q8


@dataclass(frozen=True, slots=True)
class RectTrack:
    x0: int
    y0: int
    width: int
    height: int
    dx_per_frame: int
    dy_per_frame: int
    material_index: int
    z_index: int

    def validate(self, spec: CanonicalVideoSpec, material_count: int) -> None:
        if self.width <= 0 or self.height <= 0:
            raise CASVIRError("rectangle dimensions must be positive")
        if not 0 <= self.material_index < material_count:
            raise CASVIRError("rectangle refers to an unknown material")
        if self.z_index < 0:
            raise CASVIRError("rectangle z-index must be non-negative")
        for frame_index in range(spec.frame_count):
            x = self.x0 + frame_index * self.dx_per_frame
            y = self.y0 + frame_index * self.dy_per_frame
            if x < 0 or y < 0 or x + self.width > spec.width or y + self.height > spec.height:
                raise CASVIRError("rectangle leaves the canonical frame")


@dataclass(frozen=True, slots=True)
class CausalVisualProgram:
    spec: CanonicalVideoSpec
    materials: tuple[Material, ...]
    background_material_index: int
    tracks: tuple[RectTrack, ...]
    ambient_brightness_q8: int = 255
    edge_mode: str = "PIXEL_ALIGNED_HARD"

    def validate(self) -> None:
        self.spec.validate()
        if self.spec.pixel_format != CASV_PIXEL_FORMAT:
            raise CASVIRError("the rectilinear renderer accepts only canonical RGB8 media")
        if not self.materials:
            raise CASVIRError("visual program needs at least one material")
        for material in self.materials:
            material.validate()
        if not 0 <= self.background_material_index < len(self.materials):
            raise CASVIRError("background refers to an unknown material")
        if not 0 <= self.ambient_brightness_q8 <= 255:
            raise CASVIRError("ambient brightness must fit in one byte")
        if self.edge_mode != "PIXEL_ALIGNED_HARD":
            raise CASVIRError("CASV/0.1 only implements pixel-aligned hard edges")
        seen_z: set[int] = set()
        for track in self.tracks:
            track.validate(self.spec, len(self.materials))
            if track.z_index in seen_z:
                raise CASVIRError("rectangle z-index values must be unique")
            seen_z.add(track.z_index)


@dataclass(frozen=True, slots=True)
class SceneInference:
    program: CausalVisualProgram
    rendered: bytes
    residual_xor: bytes
    exact_predicted_pixels: int
    residual_nonzero_bytes: int
    detected_tracks: int

    @property
    def total_pixels(self) -> int:
        return self.program.spec.width * self.program.spec.height * self.program.spec.frame_count


def _resolved_channel(channel: int, material_brightness: int, ambient: int) -> int:
    material_value = (channel * material_brightness + 127) // 255
    return (material_value * ambient + 127) // 255


def _resolved_color(material: Material, ambient: int) -> bytes:
    return bytes(
        (
            _resolved_channel(material.red, material.brightness_q8, ambient),
            _resolved_channel(material.green, material.brightness_q8, ambient),
            _resolved_channel(material.blue, material.brightness_q8, ambient),
        )
    )


def validate_canonical_frames(frames: bytes, spec: CanonicalVideoSpec) -> None:
    spec.validate()
    if len(frames) != spec.expected_bytes:
        raise CASVIRError(
            f"canonical payload length differs: expected {spec.expected_bytes}, got {len(frames)}"
        )


def render_visual_program(program: CausalVisualProgram) -> bytes:
    program.validate()
    spec = program.spec
    background = _resolved_color(
        program.materials[program.background_material_index],
        program.ambient_brightness_q8,
    )
    ordered_tracks = sorted(program.tracks, key=lambda item: item.z_index)
    output = bytearray()
    for frame_index in range(spec.frame_count):
        frame = bytearray(background * (spec.width * spec.height))
        for track in ordered_tracks:
            color = _resolved_color(
                program.materials[track.material_index],
                program.ambient_brightness_q8,
            )
            x = track.x0 + frame_index * track.dx_per_frame
            y = track.y0 + frame_index * track.dy_per_frame
            row = color * track.width
            for offset_y in range(track.height):
                start = ((y + offset_y) * spec.width + x) * 3
                frame[start : start + len(row)] = row
        output.extend(frame)
    return bytes(output)


def encode_visual_base(program: CausalVisualProgram) -> bytes:
    program.validate()
    spec = program.spec
    payload = bytearray(
        _BASE_HEADER.pack(
            BASE_MAGIC,
            spec.width,
            spec.height,
            spec.frame_count,
            spec.fps_numerator,
            spec.fps_denominator,
            program.background_material_index,
            len(program.materials),
            len(program.tracks),
            program.ambient_brightness_q8,
        )
    )
    for material in program.materials:
        payload.extend(_MATERIAL.pack(*material.as_tuple()))
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


def encode_temporal_dynamics(program: CausalVisualProgram) -> bytes:
    program.validate()
    ordered = sorted(program.tracks, key=lambda item: item.z_index)
    payload = bytearray(_DYNAMICS_HEADER.pack(DYNAMICS_MAGIC, len(ordered)))
    for track in ordered:
        payload.extend(_DYNAMICS_TRACK.pack(track.dx_per_frame, track.dy_per_frame))
    return bytes(payload)


def encode_visual_program(program: CausalVisualProgram) -> bytes:
    """Diagnostic concatenation; a CASV archive stores both parts separately."""

    base = encode_visual_base(program)
    dynamics = encode_temporal_dynamics(program)
    return struct.pack(">II", len(base), len(dynamics)) + base + dynamics


def _pixels(frame: memoryview) -> Iterable[tuple[int, int, int]]:
    for offset in range(0, len(frame), 3):
        yield frame[offset], frame[offset + 1], frame[offset + 2]


def _solid_rectangles(
    frame: memoryview,
    *,
    width: int,
    height: int,
    background: tuple[int, int, int],
) -> dict[tuple[tuple[int, int, int], int, int], tuple[int, int]]:
    positions: dict[tuple[int, int, int], list[tuple[int, int]]] = {}
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 3
            color = (frame[offset], frame[offset + 1], frame[offset + 2])
            if color != background:
                positions.setdefault(color, []).append((x, y))
    rectangles: dict[tuple[tuple[int, int, int], int, int], tuple[int, int]] = {}
    for color, points in positions.items():
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        rect_width = max_x - min_x + 1
        rect_height = max_y - min_y + 1
        if len(points) != rect_width * rect_height:
            continue
        key = (color, rect_width, rect_height)
        if key in rectangles:
            continue
        rectangles[key] = (min_x, min_y)
    return rectangles


def infer_rectilinear_program(frames: bytes, spec: CanonicalVideoSpec) -> SceneInference:
    """Infer a bounded deterministic scene; unexplained bytes remain in the residual."""

    validate_canonical_frames(frames, spec)
    if spec.pixel_format != CASV_PIXEL_FORMAT:
        raise CASVIRError("rectilinear inference is implemented only for RGB8")
    frame_views = [
        memoryview(frames)[index * spec.frame_bytes : (index + 1) * spec.frame_bytes]
        for index in range(spec.frame_count)
    ]
    background = Counter(pixel for frame in frame_views for pixel in _pixels(frame)).most_common(1)[0][0]
    per_frame = [
        _solid_rectangles(
            frame,
            width=spec.width,
            height=spec.height,
            background=background,
        )
        for frame in frame_views
    ]
    shared_keys = set(per_frame[0])
    for rectangles in per_frame[1:]:
        shared_keys.intersection_update(rectangles)

    tracks_with_color: list[tuple[tuple[int, int, int], RectTrack]] = []
    for key in sorted(shared_keys):
        color, rect_width, rect_height = key
        positions = [rectangles[key] for rectangles in per_frame]
        dx = positions[1][0] - positions[0][0] if len(positions) > 1 else 0
        dy = positions[1][1] - positions[0][1] if len(positions) > 1 else 0
        if any(
            position != (positions[0][0] + index * dx, positions[0][1] + index * dy)
            for index, position in enumerate(positions)
        ):
            continue
        tracks_with_color.append(
            (
                color,
                RectTrack(
                    x0=positions[0][0],
                    y0=positions[0][1],
                    width=rect_width,
                    height=rect_height,
                    dx_per_frame=dx,
                    dy_per_frame=dy,
                    material_index=0,
                    z_index=0,
                ),
            )
        )

    materials = [Material(*background)]
    tracks: list[RectTrack] = []
    for z_index, (color, track) in enumerate(tracks_with_color):
        material_index = len(materials)
        materials.append(Material(*color))
        tracks.append(
            RectTrack(
                x0=track.x0,
                y0=track.y0,
                width=track.width,
                height=track.height,
                dx_per_frame=track.dx_per_frame,
                dy_per_frame=track.dy_per_frame,
                material_index=material_index,
                z_index=z_index,
            )
        )

    program = CausalVisualProgram(
        spec=spec,
        materials=tuple(materials),
        background_material_index=0,
        tracks=tuple(tracks),
    )
    rendered = render_visual_program(program)
    residual = bytes(source ^ predicted for source, predicted in zip(frames, rendered, strict=True))
    exact_pixels = sum(
        frames[offset : offset + 3] == rendered[offset : offset + 3]
        for offset in range(0, len(frames), 3)
    )
    return SceneInference(
        program=program,
        rendered=rendered,
        residual_xor=residual,
        exact_predicted_pixels=exact_pixels,
        residual_nonzero_bytes=sum(value != 0 for value in residual),
        detected_tracks=len(tracks),
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "BASE_MAGIC",
    "CASV_EQUIVALENCE",
    "CASV_PIXEL_FORMAT",
    "CASV_PIXEL_FORMAT_BYTES",
    "CASV_RENDERER",
    "CASVIRError",
    "CanonicalVideoSpec",
    "CausalVisualProgram",
    "Material",
    "RectTrack",
    "SceneInference",
    "encode_temporal_dynamics",
    "encode_visual_base",
    "encode_visual_program",
    "infer_rectilinear_program",
    "render_visual_program",
    "sha256_bytes",
    "validate_canonical_frames",
]
