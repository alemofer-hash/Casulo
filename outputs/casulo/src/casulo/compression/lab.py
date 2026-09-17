from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - doctor reports the unavailable metric
    psutil = None

from .archive import CompressionError, pack_file, unpack_file, verify_archive
from .tooling import doctor_report, resolve_tool


class LabError(RuntimeError):
    """O laboratório não conseguiu produzir uma comparação verificável."""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_rate(value: Any) -> float | None:
    if not isinstance(value, str) or value in {"", "0/0"}:
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def video_metadata_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Projeta somente metadados suficientes para decidir o gate 8K."""

    video_streams = [
        stream
        for stream in payload.get("streams", [])
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    if not video_streams:
        raise LabError("nenhum stream de vídeo encontrado")
    primary = video_streams[0]
    width = _optional_int(primary.get("width")) or 0
    height = _optional_int(primary.get("height")) or 0
    frames = _optional_int(primary.get("nb_frames"))
    duration = _optional_float(
        primary.get("duration", payload.get("format", {}).get("duration"))
    )
    rate_literal = primary.get("avg_frame_rate") or primary.get("r_frame_rate")
    rate = _optional_rate(rate_literal)
    qualifies_8k = width >= 7680 and height >= 4320
    qualifies_protocol = bool(
        qualifies_8k
        and duration is not None
        and duration >= 10.0
        and frames is not None
        and frames >= 300
    )
    return {
        "width": width,
        "height": height,
        "qualifies_8k": qualifies_8k,
        "qualifies_protocol": qualifies_protocol,
        "codec_name": primary.get("codec_name"),
        "pixel_format": primary.get("pix_fmt"),
        "duration_seconds": duration,
        "frame_count": frames,
        "frame_rate_literal": rate_literal,
        "frame_rate_fps": rate,
        "bit_rate": payload.get("format", {}).get("bit_rate"),
        "stream_count": len(payload.get("streams", [])),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def validate_source_identity(
    source: Path,
    *,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[int, str]:
    size = source.stat().st_size
    if expected_bytes is not None and size != expected_bytes:
        raise LabError(
            f"tamanho da fonte divergente: esperado {expected_bytes}, obtido {size}"
        )
    digest = _sha256_file(source)
    if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
        raise LabError("SHA-256 da fonte diverge do protocolo congelado")
    return size, digest


def _run(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    started = time.perf_counter_ns()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    peak_rss = 0
    observed = psutil.Process(process.pid) if psutil is not None else None
    while process.poll() is None:
        if observed is not None:
            try:
                rss = observed.memory_info().rss
                rss += sum(
                    child.memory_info().rss
                    for child in observed.children(recursive=True)
                )
                peak_rss = max(peak_rss, rss)
            except (psutil.Error, OSError):
                pass
        time.sleep(0.1)
    stdout, stderr = process.communicate()
    elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
    if process.returncode != 0:
        message = (stderr or stdout).strip()
        raise LabError(
            f"ferramenta retornou {process.returncode}: {message[-2000:]}"
        )
    return {
        "seconds": elapsed,
        "returncode": process.returncode,
        "peak_rss_bytes": peak_rss or None,
    }


def _measure_callable(function: Any, /, *args: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
    stop = threading.Event()
    peak_rss = 0

    def sample() -> None:
        nonlocal peak_rss
        if psutil is None:
            return
        current = psutil.Process()
        while not stop.wait(0.1):
            try:
                peak_rss = max(peak_rss, current.memory_info().rss)
            except (psutil.Error, OSError):
                return

    sampler = threading.Thread(target=sample, name="casulo-rss-sampler", daemon=True)
    sampler.start()
    started = time.perf_counter_ns()
    try:
        result = function(*args, **kwargs)
    finally:
        elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
        stop.set()
        sampler.join(timeout=1)
    return result, {"seconds": elapsed, "peak_rss_bytes": peak_rss or None}


def _result(
    *,
    name: str,
    source: Path,
    source_hash: str,
    archive: Path,
    restored: Path,
    encode: dict[str, Any],
    decode: dict[str, Any],
    remove_restored_after_verification: bool = True,
) -> dict[str, Any]:
    restored_hash = _sha256_file(restored)
    if restored.stat().st_size != source.stat().st_size or restored_hash != source_hash:
        raise LabError(f"baseline {name} não restaurou a fonte bit a bit")
    archive_size = archive.stat().st_size
    source_size = source.stat().st_size
    result = {
        "name": name,
        "archive": str(archive),
        "archive_bytes": archive_size,
        "archive_sha256": _sha256_file(archive),
        "encode_seconds": encode["seconds"],
        "decode_seconds": decode["seconds"],
        "encode_peak_rss_bytes": encode.get("peak_rss_bytes"),
        "decode_peak_rss_bytes": decode.get("peak_rss_bytes"),
        "restored_sha256": restored_hash,
        "bit_exact": True,
        "container_ratio": None if source_size == 0 else archive_size / source_size,
        "reduction_percent": None
        if source_size == 0
        else (1.0 - archive_size / source_size) * 100.0,
    }
    if remove_restored_after_verification:
        restored.unlink()
        result["restored_retained"] = False
    return result


def classify_candidate(results: list[dict[str, Any]], source_size: int) -> dict[str, Any]:
    candidate = next(
        result for result in results if result["name"] == "casulo-lossless"
    )
    baselines = [result for result in results if result["name"] != "casulo-lossless"]
    if not candidate["bit_exact"] or not baselines or not all(
        result["bit_exact"] for result in baselines
    ):
        return {"classification": "INVALID", "reason": "round-trip ou baseline inválido"}
    best = min(baselines, key=lambda result: result["archive_bytes"])
    ratio = candidate["archive_bytes"] / best["archive_bytes"]
    source_reduction = (
        None if source_size == 0 else 1.0 - candidate["archive_bytes"] / source_size
    )
    if source_reduction is not None and source_reduction >= 0.90 and ratio <= 0.50:
        classification = "BREAKTHROUGH_CANDIDATE"
    elif ratio <= 0.75:
        classification = "SUBSTANTIAL_ADVANTAGE"
    elif ratio <= 0.90:
        classification = "MATERIAL_ADVANTAGE"
    elif ratio < 0.95:
        classification = "SMALL_ADVANTAGE"
    elif ratio <= 1.05:
        classification = "COMPETITIVE"
    else:
        classification = "NEGATIVE"
    return {
        "classification": classification,
        "best_baseline": best["name"],
        "best_baseline_bytes": best["archive_bytes"],
        "candidate_to_best_baseline_ratio": ratio,
        "candidate_smaller_than_best_baseline_percent": (1.0 - ratio) * 100.0,
        "candidate_source_reduction_percent": None
        if source_reduction is None
        else source_reduction * 100.0,
    }


def probe_video(source: str | Path) -> dict[str, Any]:
    source_path = Path(source).resolve(strict=True)
    ffprobe = resolve_tool("ffprobe")
    if ffprobe is None:
        raise LabError("ffprobe indisponível")
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        shell=False,
    )
    if completed.returncode != 0:
        raise LabError(f"ffprobe recusou o arquivo: {completed.stderr.strip()[-2000:]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LabError("ffprobe não retornou JSON válido") from exc
    evidence = video_metadata_evidence(payload)
    return {
        "schema": "casulo.lossless-video-probe/0.1",
        "source": str(source_path),
        "source_bytes": source_path.stat().st_size,
        "source_sha256": _sha256_file(source_path),
        **evidence,
    }


def run_general_baselines(
    source: str | Path,
    output: str | Path,
    *,
    casulo_profile: str = "balanced",
    chunk_size: int = 4 * 1024 * 1024,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Executa Casulo, zstd e 7-Zip e restaura todos antes de reportar tamanho."""

    source_path = Path(source).resolve(strict=True)
    output_path = Path(output).resolve(strict=False)
    if output_path.exists():
        raise LabError(f"diretório de saída já existe: {output_path}")
    output_path.mkdir(parents=True)
    source_size, source_hash = validate_source_identity(
        source_path,
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha256,
    )
    results: list[dict[str, Any]] = []

    casulo_dir = output_path / "casulo"
    casulo_dir.mkdir()
    casulo_archive = casulo_dir / f"{source_path.name}.casulo"
    casulo_restored = casulo_dir / source_path.name
    casulo_report, encoded = _measure_callable(
        pack_file,
        source_path,
        casulo_archive,
        profile=casulo_profile,
        chunk_size=chunk_size,
    )
    _, decoded = _measure_callable(unpack_file, casulo_archive, casulo_restored)
    casulo_restored_hash = _sha256_file(casulo_restored)
    casulo_bit_exact = (
        casulo_restored.stat().st_size == source_size
        and casulo_restored_hash == source_hash
    )
    if not casulo_bit_exact:
        raise LabError("Casulo não restaurou a fonte bit a bit")
    casulo_restored.unlink()
    results.append(
        {
            "name": "casulo-lossless",
            "archive": str(casulo_archive),
            "archive_bytes": casulo_archive.stat().st_size,
            "archive_sha256": casulo_report["archive_sha256"],
            "encode_seconds": encoded["seconds"],
            "decode_seconds": decoded["seconds"],
            "encode_peak_rss_bytes": encoded["peak_rss_bytes"],
            "decode_peak_rss_bytes": decoded["peak_rss_bytes"],
            "restored_sha256": casulo_restored_hash,
            "restored_retained": False,
            "bit_exact": casulo_bit_exact,
            "container_ratio": casulo_report["container_ratio"],
            "reduction_percent": casulo_report["reduction_percent"],
        }
    )

    zstd = resolve_tool("zstd")
    if zstd is None:
        raise LabError("zstd indisponível")
    zstd_dir = output_path / "zstd"
    zstd_dir.mkdir()
    zstd_archive = zstd_dir / f"{source_path.name}.zst"
    zstd_restored = zstd_dir / source_path.name
    encoded = _run(
        [str(zstd), "-T1", "-19", "-f", "-q", str(source_path), "-o", str(zstd_archive)]
    )
    decoded = _run(
        [str(zstd), "-d", "-f", "-q", str(zstd_archive), "-o", str(zstd_restored)]
    )
    results.append(
        _result(
            name="zstd-1.5.7-level19",
            source=source_path,
            source_hash=source_hash,
            archive=zstd_archive,
            restored=zstd_restored,
            encode=encoded,
            decode=decoded,
        )
    )

    seven_zip = resolve_tool("7z")
    if seven_zip is None:
        raise LabError("7-Zip indisponível")
    seven_dir = output_path / "7zip"
    seven_dir.mkdir()
    seven_archive = seven_dir / f"{source_path.name}.7z"
    seven_restore_dir = seven_dir / "restored"
    seven_restore_dir.mkdir()
    encoded = _run(
        [
            str(seven_zip),
            "a",
            "-t7z",
            "-mx=9",
            "-mmt=1",
            "-bd",
            "-y",
            str(seven_archive),
            source_path.name,
        ],
        cwd=source_path.parent,
    )
    decoded = _run(
        [
            str(seven_zip),
            "e",
            "-bd",
            "-y",
            str(seven_archive),
            f"-o{seven_restore_dir}",
        ]
    )
    seven_result = _result(
        name="7zip-26.03-ultra",
        source=source_path,
        source_hash=source_hash,
        archive=seven_archive,
        restored=seven_restore_dir / source_path.name,
        encode=encoded,
        decode=decoded,
    )
    seven_restore_dir.rmdir()
    results.append(seven_result)

    if not all(result["bit_exact"] for result in results):
        raise CompressionError("ao menos um braço não preservou a fonte")
    report = {
        "schema": "casulo.lossless-baseline/0.1",
        "source": {
            "path": str(source_path),
            "bytes": source_size,
            "sha256": source_hash,
        },
        "toolchain": doctor_report(),
        "results": results,
        "comparison": classify_candidate(results, source_size),
        "claim_boundary": "engineering smoke unless the source protocol marks real evidence",
    }
    (output_path / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def resume_general_baselines(
    source: str | Path,
    output: str | Path,
    *,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Retoma uma campanha interrompida sem refazer braços já materializados.

    Artefatos anteriores só entram no relatório depois de uma nova restauração
    bit a bit. Tempos de encode que não foram persistidos antes da interrupção
    permanecem ``None``; eles nunca são reconstruídos a partir de timestamps.
    """

    source_path = Path(source).resolve(strict=True)
    output_path = Path(output).resolve(strict=True)
    report_path = output_path / "report.json"
    if report_path.exists():
        raise LabError(f"campanha já concluída: {report_path}")
    source_size, source_hash = validate_source_identity(
        source_path,
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha256,
    )
    results: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    casulo_dir = output_path / "casulo"
    casulo_archive = casulo_dir / f"{source_path.name}.casulo"
    if not casulo_archive.is_file():
        raise LabError("artefato Casulo anterior ausente; retomada recusada")
    casulo_restored = casulo_dir / f".{source_path.name}.resume-restored"
    if casulo_restored.exists():
        raise LabError(f"restauração Casulo residual encontrada: {casulo_restored}")
    casulo_report = verify_archive(casulo_archive)
    _, decoded = _measure_callable(unpack_file, casulo_archive, casulo_restored)
    casulo_restored_hash = _sha256_file(casulo_restored)
    if casulo_restored.stat().st_size != source_size or casulo_restored_hash != source_hash:
        raise LabError("artefato Casulo recuperado não restaura a fonte bit a bit")
    casulo_restored.unlink()
    results.append(
        {
            "name": "casulo-lossless",
            "archive": str(casulo_archive),
            "archive_bytes": casulo_archive.stat().st_size,
            "archive_sha256": _sha256_file(casulo_archive),
            "encode_seconds": None,
            "encode_measurement_status": "UNAVAILABLE_INTERRUPTED_RUN",
            "decode_seconds": decoded["seconds"],
            "encode_peak_rss_bytes": None,
            "decode_peak_rss_bytes": decoded["peak_rss_bytes"],
            "restored_sha256": casulo_restored_hash,
            "restored_retained": False,
            "bit_exact": True,
            "container_ratio": casulo_archive.stat().st_size / source_size,
            "reduction_percent": (1.0 - casulo_archive.stat().st_size / source_size) * 100.0,
            "recovery_validation": casulo_report,
        }
    )
    _write_json_atomic(casulo_dir / "resume-result.json", results[-1])
    events.append({"arm": "casulo-lossless", "action": "VALIDATED_EXISTING_ARTIFACT"})

    zstd = resolve_tool("zstd")
    if zstd is None:
        raise LabError("zstd indisponível")
    zstd_dir = output_path / "zstd"
    zstd_archive = zstd_dir / f"{source_path.name}.zst"
    if not zstd_archive.is_file():
        raise LabError("artefato zstd anterior ausente; retomada recusada")
    zstd_restored = zstd_dir / f".{source_path.name}.resume-restored"
    if zstd_restored.exists():
        raise LabError(f"restauração zstd residual encontrada: {zstd_restored}")
    decoded = _run(
        [str(zstd), "-d", "-f", "-q", str(zstd_archive), "-o", str(zstd_restored)]
    )
    zstd_result = _result(
        name="zstd-1.5.7-level19",
        source=source_path,
        source_hash=source_hash,
        archive=zstd_archive,
        restored=zstd_restored,
        encode={"seconds": None, "peak_rss_bytes": None},
        decode=decoded,
    )
    zstd_result["encode_measurement_status"] = "UNAVAILABLE_INTERRUPTED_RUN"
    results.append(zstd_result)
    _write_json_atomic(zstd_dir / "resume-result.json", results[-1])
    events.append({"arm": "zstd-1.5.7-level19", "action": "VALIDATED_EXISTING_ARTIFACT"})

    seven_zip = resolve_tool("7z")
    if seven_zip is None:
        raise LabError("7-Zip indisponível")
    seven_dir = output_path / "7zip"
    seven_dir.mkdir(exist_ok=True)
    seven_archive = seven_dir / f"{source_path.name}.7z"
    if seven_archive.exists():
        probe = subprocess.run(
            [str(seven_zip), "t", "-bd", str(seven_archive)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        if probe.returncode != 0:
            rejected = output_path / "rejected"
            rejected.mkdir(exist_ok=True)
            quarantine = rejected / f"{seven_archive.name}.interrupted-partial"
            if quarantine.exists():
                raise LabError(f"colisão no arquivo de quarentena: {quarantine}")
            partial = {
                "arm": "7zip-26.03-ultra",
                "action": "QUARANTINED_INTERRUPTED_PARTIAL",
                "original_path": str(seven_archive),
                "quarantine_path": str(quarantine),
                "bytes": seven_archive.stat().st_size,
                "sha256": _sha256_file(seven_archive),
                "validation_exit_code": probe.returncode,
                "validation_stderr_tail": probe.stderr[-2000:],
            }
            seven_archive.replace(quarantine)
            _write_json_atomic(rejected / "7zip-interrupted-partial.json", partial)
            events.append(partial)
    seven_restore_dir = seven_dir / "restored"
    if seven_restore_dir.exists():
        if any(seven_restore_dir.iterdir()):
            raise LabError(f"restauração 7-Zip residual não vazia: {seven_restore_dir}")
    else:
        seven_restore_dir.mkdir()
    if seven_archive.exists():
        encoded = {
            "seconds": None,
            "peak_rss_bytes": None,
        }
        encode_status = "VALID_EXISTING_ARTIFACT"
    else:
        encoded = _run(
            [
                str(seven_zip),
                "a",
                "-t7z",
                "-mx=9",
                "-mmt=1",
                "-bd",
                "-y",
                str(seven_archive),
                source_path.name,
            ],
            cwd=source_path.parent,
        )
        encode_status = "MEASURED_DURING_RESUME"
    decoded = _run(
        [
            str(seven_zip),
            "e",
            "-bd",
            "-y",
            str(seven_archive),
            f"-o{seven_restore_dir}",
        ]
    )
    seven_result = _result(
        name="7zip-26.03-ultra",
        source=source_path,
        source_hash=source_hash,
        archive=seven_archive,
        restored=seven_restore_dir / source_path.name,
        encode=encoded,
        decode=decoded,
    )
    seven_result["encode_measurement_status"] = encode_status
    seven_restore_dir.rmdir()
    results.append(seven_result)
    _write_json_atomic(seven_dir / "resume-result.json", results[-1])
    events.append({"arm": "7zip-26.03-ultra", "action": encode_status})

    report = {
        "schema": "casulo.lossless-baseline/0.2-resumed",
        "source": {
            "path": str(source_path),
            "bytes": source_size,
            "sha256": source_hash,
        },
        "toolchain": doctor_report(),
        "results": results,
        "comparison": classify_candidate(results, source_size),
        "recovery": {
            "status": "RESUMED_WITH_EXACT_ROUND_TRIP",
            "events": events,
            "timing_limitation": (
                "encode_seconds for artifacts completed before interruption is unavailable"
            ),
        },
        "claim_boundary": "single real 8K source; no universal compression claim",
    }
    _write_json_atomic(report_path, report)
    return report
