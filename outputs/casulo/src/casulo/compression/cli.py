from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from casulo.t.productive import ProductiveTError
from casulo.t.v2_tcap import TcapV2Error

from .archive import (
    CompressionError,
    inspect_archive,
    pack_file,
    unpack_file,
    verify_archive,
)
from .casv_archive import CASVArchiveError, pack_casv_frames
from .casv_authority import CASVAuthorityError
from .casv_compact_stream import (
    CASVCompactStreamError,
    pack_casv_compact_stream_file,
)
from .casv_compact_probe import CASVCompactProbeError, run_casv_compact_probe
from .casv_compact_repack import (
    CASVCompactRepackError,
    repack_tiled_to_compact_campaign,
)
from .casv_temporal_probe import CASVTemporalProbeError, run_casv_temporal_probe
from .casv_temporal_repack import (
    CASVTemporalRepackError,
    repack_program_to_temporal_campaign,
)
from .casv_temporal_stream import (
    CASVTemporalStreamError,
    pack_casv_temporal_stream_file,
)
from .casv_import import CASVImportError, import_video_to_canonical
from .casv_ir import CASVIRError, CanonicalVideoSpec
from .casv_player import CASVPlayerError, play_casv
from .casv_probe import CASVProbeError, run_casv_probe
from .casv_program_stream import (
    CASVProgramStreamError,
    pack_casv_program_stream_file,
)
from .casv_program_probe import CASVProgramProbeError, run_casv_program_probe
from .casv_stream_archive import CASVStreamArchiveError, pack_casv_stream_file
from .casv_stream_import import (
    CASVStreamImportError,
    pack_video_to_casv_compact_stream,
    pack_video_to_casv_program_stream,
    pack_video_to_casv_stream,
    pack_video_to_casv_temporal_stream,
    pack_video_to_casv_tiled_stream,
)
from .casv_stream_probe import CASVStreamProbeError, run_casv_stream_probe
from .casv_tile_authority import CASVTileAuthorityError
from .casv_tiled_probe import CASVTiledProbeError, run_casv_tiled_probe
from .casv_tiled_stream import (
    CASVTiledStreamError,
    pack_casv_tiled_stream_file,
)
from .gop_archive import GOPArchiveError
from .gop_authority import GOPAuthorityError
from .gop_probe import run_gop_probe
from .gop_transforms import GOPTransformError
from .hevc_gop import HEVCGOPError, scan_hevc_access_units
from .independent_gop import IndependentGOPError, reconstruct_gop_independently
from .independent_casv import IndependentCASVError, reconstruct_casv_independently
from .independent_casv_compact_stream import (
    IndependentCASVCompactStreamError,
    inspect_casv_compact_stream,
    unpack_casv_compact_stream,
    verify_casv_compact_stream,
)
from .independent_casv_temporal_stream import (
    IndependentCASVTemporalStreamError,
    inspect_casv_temporal_stream,
    unpack_casv_temporal_stream,
    verify_casv_temporal_stream,
)
from .independent_casv_stream import (
    IndependentCASVStreamError,
    extract_casv_stream_frames,
    inspect_casv_stream,
    verify_casv_stream,
)
from .independent_casv_program_stream import (
    IndependentCASVProgramStreamError,
    extract_casv_program_stream_frames,
    inspect_casv_program_stream,
    verify_casv_program_stream,
)
from .independent_casv_tiled_stream import (
    IndependentCASVTiledStreamError,
    inspect_casv_tiled_stream,
    unpack_casv_tiled_stream,
    verify_casv_tiled_stream,
)
from .independent_structural import (
    IndependentReconstructionError,
    reconstruct_independently,
)
from .lab import LabError, probe_video, resume_general_baselines, run_general_baselines
from .mp4_hevc import MP4AnalysisError, analyze_mp4_hevc
from .structural_archive import StructuralArchiveError, pack_structural
from .structural_authority import StructuralAuthorityError
from .structural_probe import run_structural_probe
from .tooling import doctor_report


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STRUCTURAL_POLICY = ROOT / "examples" / "t-v2" / "compression_structural.t"
FORCE_RAW_STRUCTURAL_POLICY = (
    ROOT / "examples" / "t-v2" / "compression_structural_force_raw.t"
)
DEFAULT_GOP_POLICY = ROOT / "examples" / "t-v2" / "compression_hevc_gop.t"
FORCE_RAW_GOP_POLICY = ROOT / "examples" / "t-v2" / "compression_hevc_gop_force_raw.t"
DEFAULT_CASV_POLICY = ROOT / "examples" / "t-v2" / "compression_casv.t"
FORCE_RAW_CASV_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_force_raw.t"
DEFAULT_CASV_TILE_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_tile.t"
FORCE_RAW_CASV_TILE_POLICY = (
    ROOT / "examples" / "t-v2" / "compression_casv_tile_force_raw.t"
)
DEFAULT_CASV_COMPACT_POLICY = ROOT / "examples" / "t-v2" / "compression_casv_compact.t"
FORCE_RAW_CASV_COMPACT_POLICY = (
    ROOT / "examples" / "t-v2" / "compression_casv_compact_force_raw.t"
)
DEFAULT_CASV_TEMPORAL_POLICY = (
    ROOT / "examples" / "t-v2" / "compression_casv_temporal.t"
)
FORCE_SPATIAL_CASV_TEMPORAL_POLICY = (
    ROOT / "examples" / "t-v2" / "compression_casv_temporal_force_spatial.t"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casulo-compress",
        description="Compressão sem perda, deduplicada e verificável do Casulo.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    pack = subcommands.add_parser("pack", help="Empacota um arquivo sem perda.")
    pack.add_argument("source")
    pack.add_argument("archive")
    pack.add_argument(
        "--profile",
        choices=("fast", "balanced", "max"),
        default="balanced",
    )
    pack.add_argument("--chunk-mib", type=int, default=4)

    unpack = subcommands.add_parser("unpack", help="Reconstrói o arquivo original.")
    unpack.add_argument("archive")
    unpack.add_argument("destination")
    unpack.add_argument("--overwrite", action="store_true")

    verify = subcommands.add_parser(
        "verify", help="Verifica todos os bytes sem extrair."
    )
    verify.add_argument("archive")

    inspect = subcommands.add_parser("inspect", help="Exibe o manifesto validado.")
    inspect.add_argument("archive")
    subcommands.add_parser("doctor", help="Valida ferramentas do laboratório real.")

    video = subcommands.add_parser(
        "video-probe", help="Confirma resolução e metadados reais."
    )
    video.add_argument("source")

    baseline = subcommands.add_parser("baseline", help="Compara Casulo, zstd e 7-Zip.")
    baseline.add_argument("source")
    baseline.add_argument("output")
    baseline.add_argument(
        "--profile",
        choices=("fast", "balanced", "max"),
        default="balanced",
    )
    baseline.add_argument("--chunk-mib", type=int, default=4)
    baseline.add_argument("--expected-bytes", type=int)
    baseline.add_argument("--expected-sha256")

    resume = subcommands.add_parser(
        "resume-baseline",
        help="Retoma uma campanha interrompida validando os braços existentes.",
    )
    resume.add_argument("source")
    resume.add_argument("output")
    resume.add_argument("--expected-bytes", type=int)
    resume.add_argument("--expected-sha256")

    structural_analyze = subcommands.add_parser(
        "structural-analyze",
        help="Analisa caixas ISO BMFF e configuração HEVC com leituras limitadas.",
    )
    structural_analyze.add_argument("source")

    structural_pack = subcommands.add_parser(
        "structural-pack",
        help="Empacota pela IR base + dinâmica + residual sob autoridade T.",
    )
    structural_pack.add_argument("source")
    structural_pack.add_argument("archive")
    structural_pack.add_argument("--evidence-dir", required=True)
    structural_pack.add_argument("--policy", default=str(DEFAULT_STRUCTURAL_POLICY))
    structural_pack.add_argument("--runtime")

    structural_verify = subcommands.add_parser(
        "structural-verify",
        help="Reconstrói e verifica sem importar encoder ou runtime T.",
    )
    structural_verify.add_argument("archive")

    structural_unpack = subcommands.add_parser(
        "structural-unpack",
        help="Reconstrução independente e bit-exata para um arquivo.",
    )
    structural_unpack.add_argument("archive")
    structural_unpack.add_argument("destination")
    structural_unpack.add_argument("--overwrite", action="store_true")

    structural_probe = subcommands.add_parser(
        "structural-probe",
        help="Executa probe curto derivado de MP4 real e mutação causal T.",
    )
    structural_probe.add_argument("source")
    structural_probe.add_argument("output")
    structural_probe.add_argument("--media-mib", type=int, default=4)
    structural_probe.add_argument("--expected-source-sha256")
    structural_probe.add_argument("--runtime")

    gop_analyze = subcommands.add_parser(
        "gop-analyze",
        help="Mapeia todos os samples/GOPs e headers NAL sem ler corpos HEVC.",
    )
    gop_analyze.add_argument("source")

    gop_probe = subcommands.add_parser(
        "gop-probe",
        help="Executa probe sample-aligned com referência inter-frame reversível.",
    )
    gop_probe.add_argument("source")
    gop_probe.add_argument("output")
    gop_probe.add_argument("--target-mib", type=int, default=64)
    gop_probe.add_argument("--minimum-samples", type=int, default=2)
    gop_probe.add_argument("--expected-source-sha256")
    gop_probe.add_argument("--runtime")

    gop_verify = subcommands.add_parser(
        "gop-verify",
        help="Verifica e reconstrói em memória com decoder GOP independente.",
    )
    gop_verify.add_argument("archive")

    gop_unpack = subcommands.add_parser(
        "gop-unpack",
        help="Reconstrói corpus HEVC sample-aligned com decoder independente.",
    )
    gop_unpack.add_argument("archive")
    gop_unpack.add_argument("destination")
    gop_unpack.add_argument("--overwrite", action="store_true")

    casv_pack = subcommands.add_parser(
        "casv-pack",
        help="Compila RGB8 canônico para o formato visual generativo CASV.",
    )
    casv_pack.add_argument("source")
    casv_pack.add_argument("archive")
    casv_pack.add_argument("--width", type=int, required=True)
    casv_pack.add_argument("--height", type=int, required=True)
    casv_pack.add_argument("--frames", type=int, required=True)
    casv_pack.add_argument("--fps-numerator", type=int, required=True)
    casv_pack.add_argument("--fps-denominator", type=int, default=1)
    casv_pack.add_argument("--evidence-dir", required=True)
    casv_pack.add_argument("--policy", default=str(DEFAULT_CASV_POLICY))
    casv_pack.add_argument("--runtime")

    casv_verify = subcommands.add_parser(
        "casv-verify",
        help="Reconstrói e verifica CASV com decoder independente.",
    )
    casv_verify.add_argument("archive")

    casv_unpack = subcommands.add_parser(
        "casv-unpack",
        help="Reconstrói os quadros RGB8 canônicos de um CASV.",
    )
    casv_unpack.add_argument("archive")
    casv_unpack.add_argument("destination")
    casv_unpack.add_argument("--overwrite", action="store_true")

    casv_probe = subcommands.add_parser(
        "casv-probe",
        help="Executa validação sintética bounded do formato generativo próprio.",
    )
    casv_probe.add_argument("output")
    casv_probe.add_argument("--runtime")

    casv_import = subcommands.add_parser(
        "casv-import",
        help="Importa um prefixo bounded de vídeo para CASV sem embutir o bitstream.",
    )
    casv_import.add_argument("source")
    casv_import.add_argument("archive")
    casv_import.add_argument("--frames", type=int, required=True)
    casv_import.add_argument("--crop", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    casv_import.add_argument("--evidence-dir", required=True)
    casv_import.add_argument("--expected-source-sha256")
    casv_import.add_argument(
        "--preserve-source-pixel-format",
        action="store_true",
        help="Preserva formatos nativos suportados em vez de converter para RGB8.",
    )
    casv_import.add_argument("--policy", default=str(DEFAULT_CASV_POLICY))
    casv_import.add_argument("--runtime")

    casv_play = subcommands.add_parser(
        "casv-play",
        help="Abre CASV pelo player de referência local baseado em ffplay.",
    )
    casv_play.add_argument("archive")
    casv_play.add_argument("--ffplay")

    casv_stream_pack = subcommands.add_parser(
        "casv-stream-pack",
        help="Empacota mídia canônica no CASV/0.2 segmentado e forward-only.",
    )
    casv_stream_pack.add_argument("source")
    casv_stream_pack.add_argument("archive")
    casv_stream_pack.add_argument("--width", type=int, required=True)
    casv_stream_pack.add_argument("--height", type=int, required=True)
    casv_stream_pack.add_argument("--frames", type=int, required=True)
    casv_stream_pack.add_argument("--fps-numerator", type=int, required=True)
    casv_stream_pack.add_argument("--fps-denominator", type=int, default=1)
    casv_stream_pack.add_argument(
        "--pixel-format",
        choices=("RGB8", "YUV444P10LE"),
        default="RGB8",
    )
    casv_stream_pack.add_argument("--segment-kib", type=int, default=8192)
    casv_stream_pack.add_argument("--evidence-dir", required=True)
    casv_stream_pack.add_argument("--policy", default=str(DEFAULT_CASV_POLICY))
    casv_stream_pack.add_argument("--runtime")

    casv_stream_inspect = subcommands.add_parser(
        "casv-stream-inspect",
        help="Valida e exibe o índice hasheado de um CASV/0.2.",
    )
    casv_stream_inspect.add_argument("archive")

    casv_stream_verify = subcommands.add_parser(
        "casv-stream-verify",
        help="Verifica integralmente CASV/0.2 com memória limitada por segmento.",
    )
    casv_stream_verify.add_argument("archive")

    casv_stream_unpack = subcommands.add_parser(
        "casv-stream-unpack",
        help="Reconstrói integralmente a mídia canônica de um CASV/0.2.",
    )
    casv_stream_unpack.add_argument("archive")
    casv_stream_unpack.add_argument("destination")
    casv_stream_unpack.add_argument("--overwrite", action="store_true")

    casv_stream_extract = subcommands.add_parser(
        "casv-stream-extract",
        help="Extrai quadros selecionados validando índice e segmentos lidos.",
    )
    casv_stream_extract.add_argument("archive")
    casv_stream_extract.add_argument("destination")
    casv_stream_extract.add_argument("--start-frame", type=int, required=True)
    casv_stream_extract.add_argument("--frames", type=int, required=True)
    casv_stream_extract.add_argument("--overwrite", action="store_true")

    casv_stream_probe = subcommands.add_parser(
        "casv-stream-probe",
        help="Executa o gate sintético curto do container CASV/0.2.",
    )
    casv_stream_probe.add_argument("output")
    casv_stream_probe.add_argument("--policy", default=str(DEFAULT_CASV_POLICY))
    casv_stream_probe.add_argument("--runtime")

    casv_stream_import = subcommands.add_parser(
        "casv-stream-import",
        help="Decodifica FFmpeg stdout diretamente para CASV/0.2.",
    )
    casv_stream_import.add_argument("source")
    casv_stream_import.add_argument("archive")
    casv_stream_import.add_argument("--frames", type=int, required=True)
    casv_stream_import.add_argument(
        "--crop",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
    )
    casv_stream_import.add_argument(
        "--preserve-source-pixel-format", action="store_true"
    )
    casv_stream_import.add_argument("--segment-kib", type=int, default=8192)
    casv_stream_import.add_argument("--max-canonical-mib", type=int, default=1024)
    casv_stream_import.add_argument("--timeout-seconds", type=int, default=600)
    casv_stream_import.add_argument("--evidence-dir", required=True)
    casv_stream_import.add_argument("--expected-source-sha256")
    casv_stream_import.add_argument("--policy", default=str(DEFAULT_CASV_POLICY))
    casv_stream_import.add_argument("--runtime")

    casv_program_pack = subcommands.add_parser(
        "casv-program-pack",
        help="Empacota mídia canônica como CASV/0.3 base + dinâmica + residual.",
    )
    casv_program_pack.add_argument("source")
    casv_program_pack.add_argument("archive")
    casv_program_pack.add_argument("--width", type=int, required=True)
    casv_program_pack.add_argument("--height", type=int, required=True)
    casv_program_pack.add_argument("--frames", type=int, required=True)
    casv_program_pack.add_argument("--fps-numerator", type=int, required=True)
    casv_program_pack.add_argument("--fps-denominator", type=int, default=1)
    casv_program_pack.add_argument(
        "--pixel-format",
        choices=("RGB8", "YUV444P10LE"),
        default="RGB8",
    )
    casv_program_pack.add_argument("--frames-per-segment", type=int, default=8)
    casv_program_pack.add_argument("--evidence-dir", required=True)
    casv_program_pack.add_argument("--policy", default=str(DEFAULT_CASV_POLICY))
    casv_program_pack.add_argument("--runtime")

    casv_program_inspect = subcommands.add_parser(
        "casv-program-inspect",
        help="Valida e exibe o índice de programas causais CASV/0.3.",
    )
    casv_program_inspect.add_argument("archive")

    casv_program_verify = subcommands.add_parser(
        "casv-program-verify",
        help="Reconstrói e verifica CASV/0.3 com decoder independente.",
    )
    casv_program_verify.add_argument("archive")

    casv_program_unpack = subcommands.add_parser(
        "casv-program-unpack",
        help="Reconstrói integralmente a mídia canônica de um CASV/0.3.",
    )
    casv_program_unpack.add_argument("archive")
    casv_program_unpack.add_argument("destination")
    casv_program_unpack.add_argument("--overwrite", action="store_true")

    casv_program_extract = subcommands.add_parser(
        "casv-program-extract",
        help="Extrai quadros CASV/0.3 validando somente os segmentos lidos.",
    )
    casv_program_extract.add_argument("archive")
    casv_program_extract.add_argument("destination")
    casv_program_extract.add_argument("--start-frame", type=int, required=True)
    casv_program_extract.add_argument("--frames", type=int, required=True)
    casv_program_extract.add_argument("--overwrite", action="store_true")

    casv_program_import = subcommands.add_parser(
        "casv-program-import",
        help="Decodifica FFmpeg stdout diretamente para programas CASV/0.3.",
    )
    casv_program_import.add_argument("source")
    casv_program_import.add_argument("archive")
    casv_program_import.add_argument("--frames", type=int, required=True)
    casv_program_import.add_argument(
        "--crop",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
    )
    casv_program_import.add_argument(
        "--preserve-source-pixel-format",
        action="store_true",
    )
    casv_program_import.add_argument("--frames-per-segment", type=int, default=8)
    casv_program_import.add_argument("--max-canonical-mib", type=int, default=1024)
    casv_program_import.add_argument("--timeout-seconds", type=int, default=600)
    casv_program_import.add_argument("--evidence-dir", required=True)
    casv_program_import.add_argument("--expected-source-sha256")
    casv_program_import.add_argument("--policy", default=str(DEFAULT_CASV_POLICY))
    casv_program_import.add_argument("--runtime")

    casv_program_probe = subcommands.add_parser(
        "casv-program-probe",
        help="Executa o gate causal curto de CASV/0.3 sem mídia natural.",
    )
    casv_program_probe.add_argument("output")
    casv_program_probe.add_argument("--runtime")

    casv_tiled_pack = subcommands.add_parser(
        "casv-tiled-pack",
        help="Empacota mídia canônica como faixas e tiles reversíveis CASV/0.4.",
    )
    casv_tiled_pack.add_argument("source")
    casv_tiled_pack.add_argument("archive")
    casv_tiled_pack.add_argument("--width", type=int, required=True)
    casv_tiled_pack.add_argument("--height", type=int, required=True)
    casv_tiled_pack.add_argument("--frames", type=int, required=True)
    casv_tiled_pack.add_argument("--fps-numerator", type=int, required=True)
    casv_tiled_pack.add_argument("--fps-denominator", type=int, default=1)
    casv_tiled_pack.add_argument(
        "--pixel-format",
        choices=("RGB8", "YUV444P10LE"),
        default="RGB8",
    )
    casv_tiled_pack.add_argument("--tile-width", type=int, default=512)
    casv_tiled_pack.add_argument("--strip-height", type=int, default=128)
    casv_tiled_pack.add_argument("--evidence-dir", required=True)
    casv_tiled_pack.add_argument("--policy", default=str(DEFAULT_CASV_TILE_POLICY))
    casv_tiled_pack.add_argument("--runtime")

    casv_tiled_inspect = subcommands.add_parser(
        "casv-tiled-inspect",
        help="Valida estrutura, partição e hashes CASV/0.4.",
    )
    casv_tiled_inspect.add_argument("archive")

    casv_tiled_verify = subcommands.add_parser(
        "casv-tiled-verify",
        help="Reconstrói e verifica CASV/0.4 com decoder independente.",
    )
    casv_tiled_verify.add_argument("archive")

    casv_tiled_unpack = subcommands.add_parser(
        "casv-tiled-unpack",
        help="Reconstrói integralmente a mídia canônica de CASV/0.4.",
    )
    casv_tiled_unpack.add_argument("archive")
    casv_tiled_unpack.add_argument("destination")

    casv_tiled_import = subcommands.add_parser(
        "casv-tiled-import",
        help="Decodifica FFmpeg stdout em faixas limitadas CASV/0.4.",
    )
    casv_tiled_import.add_argument("source")
    casv_tiled_import.add_argument("archive")
    casv_tiled_import.add_argument("--frames", type=int, required=True)
    casv_tiled_import.add_argument(
        "--crop",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
    )
    casv_tiled_import.add_argument(
        "--preserve-source-pixel-format", action="store_true"
    )
    casv_tiled_import.add_argument("--tile-width", type=int, default=512)
    casv_tiled_import.add_argument("--strip-height", type=int, default=128)
    casv_tiled_import.add_argument("--max-canonical-mib", type=int, default=1024)
    casv_tiled_import.add_argument("--timeout-seconds", type=int, default=600)
    casv_tiled_import.add_argument("--evidence-dir", required=True)
    casv_tiled_import.add_argument("--expected-source-sha256")
    casv_tiled_import.add_argument("--policy", default=str(DEFAULT_CASV_TILE_POLICY))
    casv_tiled_import.add_argument("--runtime")

    casv_tiled_probe = subcommands.add_parser(
        "casv-tiled-probe",
        help="Executa o gate curto de tiling, autoridade T e corrupção CASV/0.4.",
    )
    casv_tiled_probe.add_argument("output")
    casv_tiled_probe.add_argument("--runtime")

    casv_compact_pack = subcommands.add_parser(
        "casv-compact-pack",
        help="Empacota mídia canônica no container binário compacto CASV/0.5.",
    )
    casv_compact_pack.add_argument("source")
    casv_compact_pack.add_argument("archive")
    casv_compact_pack.add_argument("--width", type=int, required=True)
    casv_compact_pack.add_argument("--height", type=int, required=True)
    casv_compact_pack.add_argument("--frames", type=int, required=True)
    casv_compact_pack.add_argument("--fps-numerator", type=int, required=True)
    casv_compact_pack.add_argument("--fps-denominator", type=int, default=1)
    casv_compact_pack.add_argument(
        "--pixel-format",
        choices=("RGB8", "YUV444P10LE"),
        default="RGB8",
    )
    casv_compact_pack.add_argument("--tile-width", type=int, default=512)
    casv_compact_pack.add_argument("--strip-height", type=int, default=128)
    casv_compact_pack.add_argument("--evidence-dir", required=True)
    casv_compact_pack.add_argument("--policy", default=str(DEFAULT_CASV_COMPACT_POLICY))
    casv_compact_pack.add_argument("--runtime")

    casv_compact_inspect = subcommands.add_parser(
        "casv-compact-inspect",
        help="Valida a estrutura e o índice binário CASV/0.5.",
    )
    casv_compact_inspect.add_argument("archive")

    casv_compact_verify = subcommands.add_parser(
        "casv-compact-verify",
        help="Reconstrói e verifica CASV/0.5 com decoder independente.",
    )
    casv_compact_verify.add_argument("archive")

    casv_compact_unpack = subcommands.add_parser(
        "casv-compact-unpack",
        help="Reconstrói integralmente a mídia canônica de CASV/0.5.",
    )
    casv_compact_unpack.add_argument("archive")
    casv_compact_unpack.add_argument("destination")

    casv_compact_import = subcommands.add_parser(
        "casv-compact-import",
        help="Decodifica FFmpeg stdout no container compacto CASV/0.5.",
    )
    casv_compact_import.add_argument("source")
    casv_compact_import.add_argument("archive")
    casv_compact_import.add_argument("--frames", type=int, required=True)
    casv_compact_import.add_argument(
        "--crop",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
    )
    casv_compact_import.add_argument(
        "--preserve-source-pixel-format",
        action="store_true",
    )
    casv_compact_import.add_argument("--tile-width", type=int, default=512)
    casv_compact_import.add_argument("--strip-height", type=int, default=128)
    casv_compact_import.add_argument("--max-canonical-mib", type=int, default=1024)
    casv_compact_import.add_argument("--timeout-seconds", type=int, default=600)
    casv_compact_import.add_argument("--evidence-dir", required=True)
    casv_compact_import.add_argument("--expected-source-sha256")
    casv_compact_import.add_argument(
        "--policy", default=str(DEFAULT_CASV_COMPACT_POLICY)
    )
    casv_compact_import.add_argument("--runtime")

    casv_compact_probe = subcommands.add_parser(
        "casv-compact-probe",
        help="Executa o gate compacto, causal, exato e fail-closed CASV/0.5.",
    )
    casv_compact_probe.add_argument("output")
    casv_compact_probe.add_argument("--runtime")

    casv_compact_repack = subcommands.add_parser(
        "casv-compact-repack-tiled",
        help="Reempacota mídia verificada CASV/0.4 para CASV/0.5 sem FFmpeg.",
    )
    casv_compact_repack.add_argument("source_archive")
    casv_compact_repack.add_argument("output")
    casv_compact_repack.add_argument("--expected-source-sha256", required=True)
    casv_compact_repack.add_argument("--tile-width", type=int, default=64)
    casv_compact_repack.add_argument("--strip-height", type=int, default=48)
    casv_compact_repack.add_argument(
        "--policy", default=str(DEFAULT_CASV_COMPACT_POLICY)
    )
    casv_compact_repack.add_argument("--runtime")

    casv_temporal_pack = subcommands.add_parser(
        "casv-temporal-pack",
        help="Empacota mídia canônica com predição temporal CASV/0.6.",
    )
    casv_temporal_pack.add_argument("source")
    casv_temporal_pack.add_argument("archive")
    casv_temporal_pack.add_argument("--width", type=int, required=True)
    casv_temporal_pack.add_argument("--height", type=int, required=True)
    casv_temporal_pack.add_argument("--frames", type=int, required=True)
    casv_temporal_pack.add_argument("--fps-numerator", type=int, required=True)
    casv_temporal_pack.add_argument("--fps-denominator", type=int, default=1)
    casv_temporal_pack.add_argument(
        "--pixel-format",
        choices=("RGB8", "YUV444P10LE"),
        default="RGB8",
    )
    casv_temporal_pack.add_argument("--tile-width", type=int, default=512)
    casv_temporal_pack.add_argument("--strip-height", type=int, default=128)
    casv_temporal_pack.add_argument("--keyframe-interval", type=int, default=8)
    casv_temporal_pack.add_argument("--evidence-dir", required=True)
    casv_temporal_pack.add_argument(
        "--policy", default=str(DEFAULT_CASV_TEMPORAL_POLICY)
    )
    casv_temporal_pack.add_argument("--runtime")

    casv_temporal_inspect = subcommands.add_parser(
        "casv-temporal-inspect",
        help="Valida estrutura, referências e índice CASV/0.6.",
    )
    casv_temporal_inspect.add_argument("archive")

    casv_temporal_verify = subcommands.add_parser(
        "casv-temporal-verify",
        help="Reconstrói e verifica CASV/0.6 com decoder independente.",
    )
    casv_temporal_verify.add_argument("archive")

    casv_temporal_unpack = subcommands.add_parser(
        "casv-temporal-unpack",
        help="Reconstrói integralmente a mídia canônica de CASV/0.6.",
    )
    casv_temporal_unpack.add_argument("archive")
    casv_temporal_unpack.add_argument("destination")

    casv_temporal_import = subcommands.add_parser(
        "casv-temporal-import",
        help="Decodifica FFmpeg stdout diretamente para CASV/0.6.",
    )
    casv_temporal_import.add_argument("source")
    casv_temporal_import.add_argument("archive")
    casv_temporal_import.add_argument("--frames", type=int, required=True)
    casv_temporal_import.add_argument(
        "--crop",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
    )
    casv_temporal_import.add_argument(
        "--preserve-source-pixel-format",
        action="store_true",
    )
    casv_temporal_import.add_argument("--tile-width", type=int, default=512)
    casv_temporal_import.add_argument("--strip-height", type=int, default=128)
    casv_temporal_import.add_argument("--keyframe-interval", type=int, default=8)
    casv_temporal_import.add_argument("--max-canonical-mib", type=int, default=1024)
    casv_temporal_import.add_argument("--timeout-seconds", type=int, default=600)
    casv_temporal_import.add_argument("--evidence-dir", required=True)
    casv_temporal_import.add_argument("--expected-source-sha256")
    casv_temporal_import.add_argument(
        "--policy", default=str(DEFAULT_CASV_TEMPORAL_POLICY)
    )
    casv_temporal_import.add_argument("--runtime")

    casv_temporal_probe = subcommands.add_parser(
        "casv-temporal-probe",
        help="Executa o gate temporal causal, exato e fail-closed CASV/0.6.",
    )
    casv_temporal_probe.add_argument("output")
    casv_temporal_probe.add_argument("--runtime")

    casv_temporal_repack = subcommands.add_parser(
        "casv-temporal-repack-program",
        help="Reempacota CASV/0.3 selado em 0.6 e executa baselines lossless.",
    )
    casv_temporal_repack.add_argument("source_archive")
    casv_temporal_repack.add_argument("output")
    casv_temporal_repack.add_argument("--expected-source-sha256", required=True)
    casv_temporal_repack.add_argument("--tile-width", type=int, default=64)
    casv_temporal_repack.add_argument("--strip-height", type=int, default=48)
    casv_temporal_repack.add_argument("--keyframe-interval", type=int, default=8)
    casv_temporal_repack.add_argument(
        "--policy", default=str(DEFAULT_CASV_TEMPORAL_POLICY)
    )
    casv_temporal_repack.add_argument("--runtime")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "pack":
            result = pack_file(
                args.source,
                args.archive,
                profile=args.profile,
                chunk_size=args.chunk_mib * 1024 * 1024,
            )
        elif args.command == "unpack":
            result = unpack_file(
                args.archive,
                args.destination,
                overwrite=args.overwrite,
            )
        elif args.command == "verify":
            result = verify_archive(args.archive)
        elif args.command == "inspect":
            result = inspect_archive(args.archive)
        elif args.command == "video-probe":
            result = probe_video(args.source)
        elif args.command == "baseline":
            result = run_general_baselines(
                args.source,
                args.output,
                casulo_profile=args.profile,
                chunk_size=args.chunk_mib * 1024 * 1024,
                expected_bytes=args.expected_bytes,
                expected_sha256=args.expected_sha256,
            )
        elif args.command == "resume-baseline":
            result = resume_general_baselines(
                args.source,
                args.output,
                expected_bytes=args.expected_bytes,
                expected_sha256=args.expected_sha256,
            )
        elif args.command == "structural-analyze":
            result = analyze_mp4_hevc(args.source)
        elif args.command == "structural-pack":
            result = pack_structural(
                args.source,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
            )
        elif args.command == "structural-verify":
            result = reconstruct_independently(args.archive)
        elif args.command == "structural-unpack":
            result = reconstruct_independently(
                args.archive,
                args.destination,
                overwrite=args.overwrite,
            )
        elif args.command == "structural-probe":
            if args.media_mib <= 0 or args.media_mib > 64:
                raise ValueError(
                    "--media-mib precisa estar entre 1 e 64 para um probe curto"
                )
            result = run_structural_probe(
                args.source,
                args.output,
                default_policy=DEFAULT_STRUCTURAL_POLICY,
                force_raw_policy=FORCE_RAW_STRUCTURAL_POLICY,
                runtime=args.runtime,
                media_payload_bytes=args.media_mib * 1024 * 1024,
                accepted_source_sha256=args.expected_source_sha256,
            )
        elif args.command == "gop-analyze":
            result = scan_hevc_access_units(args.source)
        elif args.command == "gop-probe":
            if args.target_mib <= 0 or args.target_mib > 128:
                raise ValueError("--target-mib precisa estar entre 1 e 128")
            if args.minimum_samples < 2 or args.minimum_samples > 8:
                raise ValueError("--minimum-samples precisa estar entre 2 e 8")
            result = run_gop_probe(
                args.source,
                args.output,
                default_policy=DEFAULT_GOP_POLICY,
                force_raw_policy=FORCE_RAW_GOP_POLICY,
                runtime=args.runtime,
                target_bytes=args.target_mib * 1024 * 1024,
                minimum_samples=args.minimum_samples,
                accepted_source_sha256=args.expected_source_sha256,
            )
        elif args.command == "gop-verify":
            result = reconstruct_gop_independently(args.archive)
        elif args.command == "gop-unpack":
            result = reconstruct_gop_independently(
                args.archive,
                args.destination,
                overwrite=args.overwrite,
            )
        elif args.command == "casv-pack":
            source = Path(args.source).resolve()
            spec = CanonicalVideoSpec(
                width=args.width,
                height=args.height,
                frame_count=args.frames,
                fps_numerator=args.fps_numerator,
                fps_denominator=args.fps_denominator,
            )
            result = pack_casv_frames(
                source.read_bytes(),
                spec,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                source_label=source.name,
            )
        elif args.command == "casv-verify":
            result = reconstruct_casv_independently(args.archive)
        elif args.command == "casv-unpack":
            result = reconstruct_casv_independently(
                args.archive,
                args.destination,
                overwrite=args.overwrite,
            )
        elif args.command == "casv-probe":
            result = run_casv_probe(
                args.output,
                default_policy=DEFAULT_CASV_POLICY,
                force_raw_policy=FORCE_RAW_CASV_POLICY,
                runtime=args.runtime,
            )
        elif args.command == "casv-import":
            imported = import_video_to_canonical(
                args.source,
                max_frames=args.frames,
                crop=tuple(args.crop) if args.crop is not None else None,
                preserve_source_pixel_format=args.preserve_source_pixel_format,
                expected_source_sha256=args.expected_source_sha256,
            )
            result = pack_casv_frames(
                imported.frames,
                imported.spec,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                source_label=Path(args.source).name,
                source_provenance=imported.provenance,
            )
        elif args.command == "casv-play":
            result = play_casv(args.archive, ffplay_path=args.ffplay)
        elif args.command == "casv-stream-pack":
            if args.segment_kib <= 0:
                raise ValueError("--segment-kib precisa ser positivo")
            spec = CanonicalVideoSpec(
                width=args.width,
                height=args.height,
                frame_count=args.frames,
                fps_numerator=args.fps_numerator,
                fps_denominator=args.fps_denominator,
                pixel_format=args.pixel_format,
            )
            result = pack_casv_stream_file(
                args.source,
                spec,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                segment_bytes=args.segment_kib * 1024,
            )
        elif args.command == "casv-stream-inspect":
            result = inspect_casv_stream(args.archive)
        elif args.command == "casv-stream-verify":
            result = verify_casv_stream(args.archive)
        elif args.command == "casv-stream-unpack":
            result = verify_casv_stream(
                args.archive,
                args.destination,
                overwrite=args.overwrite,
            )
        elif args.command == "casv-stream-extract":
            result = extract_casv_stream_frames(
                args.archive,
                args.destination,
                start_frame=args.start_frame,
                frame_count=args.frames,
                overwrite=args.overwrite,
            )
        elif args.command == "casv-stream-probe":
            result = run_casv_stream_probe(
                args.output,
                policy_source=args.policy,
                runtime=args.runtime,
            )
        elif args.command == "casv-stream-import":
            if args.segment_kib <= 0:
                raise ValueError("--segment-kib precisa ser positivo")
            if args.max_canonical_mib <= 0:
                raise ValueError("--max-canonical-mib precisa ser positivo")
            result = pack_video_to_casv_stream(
                args.source,
                args.archive,
                frame_count=args.frames,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                crop=tuple(args.crop) if args.crop is not None else None,
                preserve_source_pixel_format=args.preserve_source_pixel_format,
                expected_source_sha256=args.expected_source_sha256,
                segment_bytes=args.segment_kib * 1024,
                timeout_seconds=args.timeout_seconds,
                maximum_canonical_bytes=args.max_canonical_mib * 1024 * 1024,
            )
        elif args.command == "casv-program-pack":
            if args.frames_per_segment <= 0:
                raise ValueError("--frames-per-segment precisa ser positivo")
            spec = CanonicalVideoSpec(
                width=args.width,
                height=args.height,
                frame_count=args.frames,
                fps_numerator=args.fps_numerator,
                fps_denominator=args.fps_denominator,
                pixel_format=args.pixel_format,
            )
            result = pack_casv_program_stream_file(
                args.source,
                spec,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                frames_per_segment=args.frames_per_segment,
            )
        elif args.command == "casv-program-inspect":
            result = inspect_casv_program_stream(args.archive)
        elif args.command == "casv-program-verify":
            result = verify_casv_program_stream(args.archive)
        elif args.command == "casv-program-unpack":
            result = verify_casv_program_stream(
                args.archive,
                args.destination,
                overwrite=args.overwrite,
            )
        elif args.command == "casv-program-extract":
            result = extract_casv_program_stream_frames(
                args.archive,
                args.destination,
                start_frame=args.start_frame,
                frame_count=args.frames,
                overwrite=args.overwrite,
            )
        elif args.command == "casv-program-import":
            if args.frames_per_segment <= 0:
                raise ValueError("--frames-per-segment precisa ser positivo")
            if args.max_canonical_mib <= 0:
                raise ValueError("--max-canonical-mib precisa ser positivo")
            result = pack_video_to_casv_program_stream(
                args.source,
                args.archive,
                frame_count=args.frames,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                crop=tuple(args.crop) if args.crop is not None else None,
                preserve_source_pixel_format=args.preserve_source_pixel_format,
                expected_source_sha256=args.expected_source_sha256,
                frames_per_segment=args.frames_per_segment,
                timeout_seconds=args.timeout_seconds,
                maximum_canonical_bytes=args.max_canonical_mib * 1024 * 1024,
            )
        elif args.command == "casv-program-probe":
            result = run_casv_program_probe(
                args.output,
                default_policy=DEFAULT_CASV_POLICY,
                force_raw_policy=FORCE_RAW_CASV_POLICY,
                runtime=args.runtime,
            )
        elif args.command == "casv-tiled-pack":
            spec = CanonicalVideoSpec(
                width=args.width,
                height=args.height,
                frame_count=args.frames,
                fps_numerator=args.fps_numerator,
                fps_denominator=args.fps_denominator,
                pixel_format=args.pixel_format,
            )
            result = pack_casv_tiled_stream_file(
                args.source,
                spec,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
            )
        elif args.command == "casv-tiled-inspect":
            result = inspect_casv_tiled_stream(args.archive)
        elif args.command == "casv-tiled-verify":
            result = verify_casv_tiled_stream(args.archive)
        elif args.command == "casv-tiled-unpack":
            result = unpack_casv_tiled_stream(args.archive, args.destination)
        elif args.command == "casv-tiled-import":
            if args.max_canonical_mib <= 0:
                raise ValueError("--max-canonical-mib precisa ser positivo")
            result = pack_video_to_casv_tiled_stream(
                args.source,
                args.archive,
                frame_count=args.frames,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                crop=tuple(args.crop) if args.crop is not None else None,
                preserve_source_pixel_format=args.preserve_source_pixel_format,
                expected_source_sha256=args.expected_source_sha256,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
                timeout_seconds=args.timeout_seconds,
                maximum_canonical_bytes=args.max_canonical_mib * 1024 * 1024,
            )
        elif args.command == "casv-tiled-probe":
            result = run_casv_tiled_probe(
                args.output,
                default_policy=DEFAULT_CASV_TILE_POLICY,
                force_raw_policy=FORCE_RAW_CASV_TILE_POLICY,
                runtime=args.runtime,
            )
        elif args.command == "casv-compact-pack":
            spec = CanonicalVideoSpec(
                width=args.width,
                height=args.height,
                frame_count=args.frames,
                fps_numerator=args.fps_numerator,
                fps_denominator=args.fps_denominator,
                pixel_format=args.pixel_format,
            )
            result = pack_casv_compact_stream_file(
                args.source,
                spec,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
            )
        elif args.command == "casv-compact-inspect":
            result = inspect_casv_compact_stream(args.archive)
        elif args.command == "casv-compact-verify":
            result = verify_casv_compact_stream(args.archive)
        elif args.command == "casv-compact-unpack":
            result = unpack_casv_compact_stream(args.archive, args.destination)
        elif args.command == "casv-compact-import":
            if args.max_canonical_mib <= 0:
                raise ValueError("--max-canonical-mib precisa ser positivo")
            result = pack_video_to_casv_compact_stream(
                args.source,
                args.archive,
                frame_count=args.frames,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                crop=tuple(args.crop) if args.crop is not None else None,
                preserve_source_pixel_format=args.preserve_source_pixel_format,
                expected_source_sha256=args.expected_source_sha256,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
                timeout_seconds=args.timeout_seconds,
                maximum_canonical_bytes=args.max_canonical_mib * 1024 * 1024,
            )
        elif args.command == "casv-compact-probe":
            result = run_casv_compact_probe(
                args.output,
                default_policy=DEFAULT_CASV_COMPACT_POLICY,
                force_raw_policy=FORCE_RAW_CASV_COMPACT_POLICY,
                runtime=args.runtime,
            )
        elif args.command == "casv-compact-repack-tiled":
            result = repack_tiled_to_compact_campaign(
                args.source_archive,
                args.output,
                expected_source_archive_sha256=args.expected_source_sha256,
                policy_source=args.policy,
                runtime=args.runtime,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
            )
        elif args.command == "casv-temporal-pack":
            spec = CanonicalVideoSpec(
                width=args.width,
                height=args.height,
                frame_count=args.frames,
                fps_numerator=args.fps_numerator,
                fps_denominator=args.fps_denominator,
                pixel_format=args.pixel_format,
            )
            result = pack_casv_temporal_stream_file(
                args.source,
                spec,
                args.archive,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
                keyframe_interval=args.keyframe_interval,
            )
        elif args.command == "casv-temporal-inspect":
            result = inspect_casv_temporal_stream(args.archive)
        elif args.command == "casv-temporal-verify":
            result = verify_casv_temporal_stream(args.archive)
        elif args.command == "casv-temporal-unpack":
            result = unpack_casv_temporal_stream(args.archive, args.destination)
        elif args.command == "casv-temporal-import":
            if args.max_canonical_mib <= 0:
                raise ValueError("--max-canonical-mib precisa ser positivo")
            result = pack_video_to_casv_temporal_stream(
                args.source,
                args.archive,
                frame_count=args.frames,
                evidence_dir=args.evidence_dir,
                policy_source=args.policy,
                runtime=args.runtime,
                crop=tuple(args.crop) if args.crop is not None else None,
                preserve_source_pixel_format=args.preserve_source_pixel_format,
                expected_source_sha256=args.expected_source_sha256,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
                keyframe_interval=args.keyframe_interval,
                timeout_seconds=args.timeout_seconds,
                maximum_canonical_bytes=args.max_canonical_mib * 1024 * 1024,
            )
        elif args.command == "casv-temporal-probe":
            result = run_casv_temporal_probe(
                args.output,
                default_policy=DEFAULT_CASV_TEMPORAL_POLICY,
                force_spatial_policy=FORCE_SPATIAL_CASV_TEMPORAL_POLICY,
                runtime=args.runtime,
            )
        elif args.command == "casv-temporal-repack-program":
            result = repack_program_to_temporal_campaign(
                args.source_archive,
                args.output,
                expected_source_archive_sha256=args.expected_source_sha256,
                policy_source=args.policy,
                runtime=args.runtime,
                tile_width=args.tile_width,
                strip_height=args.strip_height,
                keyframe_interval=args.keyframe_interval,
            )
        else:
            result = doctor_report()
    except (
        CompressionError,
        CASVArchiveError,
        CASVAuthorityError,
        CASVCompactProbeError,
        CASVCompactRepackError,
        CASVCompactStreamError,
        CASVTemporalProbeError,
        CASVTemporalRepackError,
        CASVTemporalStreamError,
        CASVImportError,
        CASVIRError,
        CASVPlayerError,
        CASVProbeError,
        CASVProgramProbeError,
        CASVProgramStreamError,
        CASVStreamArchiveError,
        CASVStreamImportError,
        CASVStreamProbeError,
        CASVTileAuthorityError,
        CASVTiledProbeError,
        CASVTiledStreamError,
        GOPArchiveError,
        GOPAuthorityError,
        GOPTransformError,
        HEVCGOPError,
        IndependentGOPError,
        IndependentCASVError,
        IndependentCASVCompactStreamError,
        IndependentCASVTemporalStreamError,
        IndependentCASVProgramStreamError,
        IndependentCASVStreamError,
        IndependentCASVTiledStreamError,
        IndependentReconstructionError,
        LabError,
        MP4AnalysisError,
        OSError,
        ProductiveTError,
        StructuralArchiveError,
        StructuralAuthorityError,
        TcapV2Error,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
