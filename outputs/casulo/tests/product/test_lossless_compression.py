from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from casulo.compression import CompressionError, pack_file, unpack_file, verify_archive
from casulo.compression.lab import (
    LabError,
    classify_candidate,
    resume_general_baselines,
    validate_source_identity,
    video_metadata_evidence,
)
from casulo.compression.tooling import resolve_tool


class LosslessCompressionTests(unittest.TestCase):
    def test_resume_validates_completed_arms_and_quarantines_partial_7zip(self) -> None:
        zstd = resolve_tool("zstd")
        seven_zip = resolve_tool("7z")
        if zstd is None or seven_zip is None:
            self.skipTest("zstd e 7-Zip são necessários para a retomada integrada")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes((b"casulo-resume-proof" * 10_000) + bytes(range(256)))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            arms = root / "arms"
            casulo_dir = arms / "casulo"
            zstd_dir = arms / "zstd"
            seven_dir = arms / "7zip"
            casulo_dir.mkdir(parents=True)
            zstd_dir.mkdir()
            seven_dir.mkdir()
            pack_file(source, casulo_dir / "source.bin.casulo", chunk_size=64 * 1024)
            completed = subprocess.run(
                [
                    str(zstd),
                    "-T1",
                    "-1",
                    "-f",
                    "-q",
                    str(source),
                    "-o",
                    str(zstd_dir / "source.bin.zst"),
                ],
                check=False,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            (seven_dir / "source.bin.7z").write_bytes(b"interrupted-not-an-archive")

            report = resume_general_baselines(
                source,
                arms,
                expected_bytes=source.stat().st_size,
                expected_sha256=digest,
            )

            self.assertEqual(report["recovery"]["status"], "RESUMED_WITH_EXACT_ROUND_TRIP")
            self.assertTrue(all(result["bit_exact"] for result in report["results"]))
            self.assertIsNone(report["results"][0]["encode_seconds"])
            self.assertIsNone(report["results"][1]["encode_seconds"])
            self.assertTrue((arms / "rejected" / "source.bin.7z.interrupted-partial").is_file())
            self.assertTrue((arms / "report.json").is_file())

    def test_frozen_source_identity_rejects_a_same_name_tampered_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"original-source")
            expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            size, digest = validate_source_identity(
                source,
                expected_bytes=len(b"original-source"),
                expected_sha256=expected_hash,
            )
            self.assertEqual(size, len(b"original-source"))
            self.assertEqual(digest, expected_hash)

            source.write_bytes(b"tampered-source")
            with self.assertRaisesRegex(LabError, "SHA-256"):
                validate_source_identity(
                    source,
                    expected_bytes=len(b"original-source"),
                    expected_sha256=expected_hash,
                )

    def test_classification_boundaries_are_total_before_real_results(self) -> None:
        def classified(candidate: int, baseline: int, source: int = 10_000) -> str:
            return classify_candidate(
                [
                    {"name": "casulo-lossless", "archive_bytes": candidate, "bit_exact": True},
                    {"name": "zstd", "archive_bytes": baseline, "bit_exact": True},
                ],
                source,
            )["classification"]

        self.assertEqual(classified(400, 1_000), "BREAKTHROUGH_CANDIDATE")
        self.assertEqual(classified(700, 1_000), "SUBSTANTIAL_ADVANTAGE")
        self.assertEqual(classified(850, 1_000), "MATERIAL_ADVANTAGE")
        self.assertEqual(classified(930, 1_000), "SMALL_ADVANTAGE")
        self.assertEqual(classified(1_000, 1_000), "COMPETITIVE")
        self.assertEqual(classified(1_100, 1_000), "NEGATIVE")

    def test_video_protocol_requires_real_8k_duration_and_frames(self) -> None:
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 8192,
                    "height": 4320,
                    "pix_fmt": "yuv444p10le",
                    "avg_frame_rate": "60000/1001",
                    "duration": "10.010000",
                    "nb_frames": "600",
                }
            ],
            "format": {"duration": "10.010000", "bit_rate": "14690817308"},
        }

        evidence = video_metadata_evidence(payload)

        self.assertTrue(evidence["qualifies_8k"])
        self.assertTrue(evidence["qualifies_protocol"])
        self.assertEqual(evidence["frame_count"], 600)
        self.assertAlmostEqual(evidence["frame_rate_fps"], 59.94005994)

    def test_video_protocol_fails_closed_when_frame_count_is_absent(self) -> None:
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 8192,
                    "height": 4320,
                    "duration": "10.1",
                    "avg_frame_rate": "60/1",
                }
            ]
        }

        evidence = video_metadata_evidence(payload)

        self.assertTrue(evidence["qualifies_8k"])
        self.assertFalse(evidence["qualifies_protocol"])
    def test_repetitive_file_round_trips_bit_exactly_and_shrinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "database.bin"
            archive = root / "database.casulo"
            restored = root / "database.restored.bin"
            source.write_bytes(
                (b"casulo-information-traffic\0" * 100_000) + bytes(range(256))
            )

            report = pack_file(source, archive, chunk_size=64 * 1024)
            verification = verify_archive(archive)
            restoration = unpack_file(archive, restored)

            self.assertTrue(report["verified"])
            self.assertTrue(verification["verified"])
            self.assertTrue(restoration["verified"])
            self.assertLess(archive.stat().st_size, source.stat().st_size)
            self.assertEqual(source.read_bytes(), restored.read_bytes())
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                restoration["restored_sha256"],
            )

    def test_incompressible_input_is_not_reported_as_a_false_win(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "noise.bin"
            archive = root / "noise.casulo"
            source.write_bytes(os.urandom(512 * 1024))

            report = pack_file(
                source,
                archive,
                profile="fast",
                chunk_size=64 * 1024,
            )

            self.assertTrue(report["verified"])
            self.assertGreater(report["container_ratio"], 1.0)
            self.assertLess(report["reduction_percent"], 0.0)

    def test_duplicate_chunks_are_stored_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "duplicates.bin"
            archive = root / "duplicates.casulo"
            block = bytes(range(256)) * 256
            source.write_bytes(block * 8)

            report = pack_file(
                source,
                archive,
                profile="fast",
                chunk_size=len(block),
            )

            self.assertEqual(report["chunk_references"], 8)
            self.assertEqual(report["unique_chunks"], 1)
            self.assertEqual(report["deduplicated_bytes"], len(block) * 7)

    def test_archive_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            first = root / "first.casulo"
            second = root / "second.casulo"
            source.write_bytes(b"A" * 200_000 + b"B" * 100_000)

            pack_file(source, first, chunk_size=64 * 1024)
            pack_file(source, second, chunk_size=64 * 1024)

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_payload_corruption_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            archive = root / "source.casulo"
            corrupted = root / "corrupted.casulo"
            source.write_bytes(b"integrity" * 20_000)
            pack_file(source, archive, chunk_size=64 * 1024)

            with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(
                corrupted,
                "w",
                allowZip64=True,
            ) as altered:
                changed = False
                for info in original.infolist():
                    payload = original.read(info.filename)
                    if not changed and info.filename.startswith("chunks/"):
                        payload = bytes([payload[0] ^ 1]) + payload[1:]
                        changed = True
                    altered.writestr(info, payload)

            with self.assertRaisesRegex(CompressionError, "hash do payload divergente"):
                verify_archive(corrupted)

    def test_overwrite_is_denied_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            archive = root / "source.casulo"
            restored = root / "restored.bin"
            source.write_bytes(b"casulo" * 20_000)
            restored.write_bytes(b"preserve")
            pack_file(source, archive, chunk_size=64 * 1024)

            with self.assertRaisesRegex(CompressionError, "destino já existe"):
                unpack_file(archive, restored)
            self.assertEqual(restored.read_bytes(), b"preserve")

    def test_empty_file_round_trips_without_inventing_a_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "empty.bin"
            archive = root / "empty.casulo"
            restored = root / "restored.bin"
            source.write_bytes(b"")

            report = pack_file(source, archive, chunk_size=64 * 1024)
            unpack_file(archive, restored)

            self.assertIsNone(report["container_ratio"])
            self.assertIsNone(report["reduction_percent"])
            self.assertEqual(restored.read_bytes(), b"")

    def test_unexpected_archive_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            archive = root / "source.casulo"
            altered = root / "altered.casulo"
            source.write_bytes(b"casulo" * 20_000)
            pack_file(source, archive, chunk_size=64 * 1024)

            with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(
                altered,
                "w",
                allowZip64=True,
            ) as output:
                for info in original.infolist():
                    output.writestr(info, original.read(info.filename))
                output.writestr("../escape.bin", b"denied")

            with self.assertRaisesRegex(CompressionError, "entradas ausentes ou inesperadas"):
                verify_archive(altered)

    def test_forged_accounting_is_rejected_instead_of_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            archive = root / "source.casulo"
            altered = root / "altered.casulo"
            source.write_bytes((b"A" * 64 * 1024) * 4)
            pack_file(source, archive, chunk_size=64 * 1024)

            with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(
                altered,
                "w",
                allowZip64=True,
            ) as output:
                for info in original.infolist():
                    payload = original.read(info.filename)
                    if info.filename == "manifest.json":
                        manifest = json.loads(payload.decode("utf-8"))
                        manifest["accounting"]["deduplicated_bytes"] = 999_999_999
                        payload = (
                            json.dumps(
                                manifest,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                            + b"\n"
                        )
                    output.writestr(info, payload)

            with self.assertRaisesRegex(
                CompressionError,
                "contabilidade do manifest diverge dos chunks",
            ):
                verify_archive(altered)


if __name__ == "__main__":
    unittest.main()
