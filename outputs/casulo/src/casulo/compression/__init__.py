"""Compressão conservativa e verificável do tráfego de informação."""

from .archive import (
    CompressionError,
    inspect_archive,
    pack_file,
    unpack_file,
    verify_archive,
)
from .casv_archive import pack_casv_frames
from .casv_audio import CanonicalAudioSpec, validate_canonical_audio
from .casv_compact_stream import (
    pack_casv_compact_stream_file,
    pack_casv_compact_stream_reader,
)
from .casv_compact_probe import run_casv_compact_probe
from .casv_compact_repack import repack_tiled_to_compact_campaign
from .casv_temporal_probe import run_casv_temporal_probe
from .casv_temporal_repack import repack_program_to_temporal_campaign
from .casv_temporal_stream import (
    pack_casv_temporal_stream_file,
    pack_casv_temporal_stream_reader,
)
from .casv_motion_campaign import run_motion_holdout_campaign
from .casv_motion_stream import (
    pack_casv_motion_stream_file,
    pack_casv_motion_stream_reader,
)
from .casv_import import (
    import_video_to_canonical,
    import_video_to_canonical_rgb8,
    prepare_video_decode_plan,
)
from .casv_ir import CanonicalVideoSpec
from .casv_player import play_casv
from .casv_probe import run_casv_probe
from .casv_stream_archive import pack_casv_stream_file, pack_casv_stream_reader
from .casv_stream_import import (
    pack_video_to_casv_compact_stream,
    pack_video_to_casv_stream,
    pack_video_to_casv_temporal_stream,
    pack_video_to_casv_tiled_stream,
)
from .casv_stream_probe import run_casv_stream_probe
from .casv_tiled_probe import run_casv_tiled_probe
from .casv_tiled_stream import (
    pack_casv_tiled_stream_file,
    pack_casv_tiled_stream_reader,
)
from .independent_casv import reconstruct_casv_independently
from .independent_casv_stream import (
    extract_casv_stream_frames,
    inspect_casv_stream,
    verify_casv_stream,
)
from .independent_casv_compact_stream import (
    inspect_casv_compact_stream,
    unpack_casv_compact_stream,
    verify_casv_compact_stream,
)
from .independent_casv_temporal_stream import (
    inspect_casv_temporal_stream,
    unpack_casv_temporal_stream,
    verify_casv_temporal_stream,
)
from .independent_casv_motion_stream import (
    inspect_casv_motion_stream,
    unpack_casv_motion_stream,
    verify_casv_motion_stream,
)
from .independent_casv_tiled_stream import (
    inspect_casv_tiled_stream,
    unpack_casv_tiled_stream,
    verify_casv_tiled_stream,
)
from .independent_structural import reconstruct_independently
from .hevc_gop import scan_hevc_access_units
from .independent_gop import reconstruct_gop_independently
from .mp4_hevc import analyze_mp4_hevc
from .gop_probe import run_gop_probe
from .structural_archive import pack_structural

__all__ = [
    "CompressionError",
    "CanonicalAudioSpec",
    "CanonicalVideoSpec",
    "import_video_to_canonical",
    "import_video_to_canonical_rgb8",
    "prepare_video_decode_plan",
    "inspect_archive",
    "pack_file",
    "pack_casv_frames",
    "pack_casv_compact_stream_file",
    "pack_casv_compact_stream_reader",
    "run_casv_compact_probe",
    "repack_tiled_to_compact_campaign",
    "run_casv_temporal_probe",
    "repack_program_to_temporal_campaign",
    "pack_casv_temporal_stream_file",
    "pack_casv_temporal_stream_reader",
    "pack_casv_motion_stream_file",
    "pack_casv_motion_stream_reader",
    "run_motion_holdout_campaign",
    "pack_casv_stream_file",
    "pack_casv_stream_reader",
    "pack_video_to_casv_stream",
    "pack_video_to_casv_compact_stream",
    "pack_video_to_casv_temporal_stream",
    "pack_video_to_casv_tiled_stream",
    "pack_casv_tiled_stream_file",
    "pack_casv_tiled_stream_reader",
    "run_casv_stream_probe",
    "run_casv_tiled_probe",
    "play_casv",
    "pack_structural",
    "analyze_mp4_hevc",
    "scan_hevc_access_units",
    "reconstruct_independently",
    "reconstruct_casv_independently",
    "extract_casv_stream_frames",
    "inspect_casv_stream",
    "inspect_casv_compact_stream",
    "verify_casv_stream",
    "unpack_casv_compact_stream",
    "verify_casv_compact_stream",
    "inspect_casv_temporal_stream",
    "unpack_casv_temporal_stream",
    "verify_casv_temporal_stream",
    "inspect_casv_motion_stream",
    "unpack_casv_motion_stream",
    "verify_casv_motion_stream",
    "inspect_casv_tiled_stream",
    "unpack_casv_tiled_stream",
    "verify_casv_tiled_stream",
    "reconstruct_gop_independently",
    "run_gop_probe",
    "run_casv_probe",
    "unpack_file",
    "validate_canonical_audio",
    "verify_archive",
]
