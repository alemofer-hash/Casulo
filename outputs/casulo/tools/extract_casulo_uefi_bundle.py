#!/usr/bin/env python3
"""Extract the three non-destructive Casulo UEFI files from a sealed image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ESP_TYPE = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FatImage:
    def __init__(self, image: Path) -> None:
        self.image = image.resolve(strict=True)
        if not self.image.is_file() or self.image.is_symlink():
            raise ValueError("image must be an ordinary file")
        self.handle = self.image.open("rb")
        self.partition_lba = self._esp_partition_lba()
        self.partition_offset = self.partition_lba * 512
        self.handle.seek(self.partition_offset)
        boot = self.handle.read(512)
        if len(boot) != 512 or boot[510:512] != b"\x55\xaa":
            raise ValueError("invalid FAT boot sector")
        self.bytes_per_sector = struct.unpack_from("<H", boot, 11)[0]
        self.sectors_per_cluster = boot[13]
        self.reserved = struct.unpack_from("<H", boot, 14)[0]
        self.fats = boot[16]
        self.root_entries = struct.unpack_from("<H", boot, 17)[0]
        total16 = struct.unpack_from("<H", boot, 19)[0]
        total32 = struct.unpack_from("<I", boot, 32)[0]
        self.total_sectors = total16 or total32
        fat16 = struct.unpack_from("<H", boot, 22)[0]
        fat32 = struct.unpack_from("<I", boot, 36)[0]
        self.fat_sectors = fat16 or fat32
        if (
            self.bytes_per_sector not in (512, 1024, 2048, 4096)
            or self.sectors_per_cluster == 0
            or self.fats == 0
            or self.fat_sectors == 0
        ):
            raise ValueError("unsupported FAT geometry")
        root_sectors = (self.root_entries * 32 + self.bytes_per_sector - 1) // self.bytes_per_sector
        data_sectors = self.total_sectors - self.reserved - self.fats * self.fat_sectors - root_sectors
        clusters = data_sectors // self.sectors_per_cluster
        self.fat_bits = 12 if clusters < 4085 else 16 if clusters < 65525 else 32
        self.root_cluster = struct.unpack_from("<I", boot, 44)[0] if self.fat_bits == 32 else 0
        self.root_offset = self.partition_offset + (
            self.reserved + self.fats * self.fat_sectors
        ) * self.bytes_per_sector
        self.data_offset = self.root_offset + root_sectors * self.bytes_per_sector
        self.cluster_bytes = self.bytes_per_sector * self.sectors_per_cluster
        self.handle.seek(self.partition_offset + self.reserved * self.bytes_per_sector)
        self.fat = self.handle.read(self.fat_sectors * self.bytes_per_sector)

    def close(self) -> None:
        self.handle.close()

    def _esp_partition_lba(self) -> int:
        self.handle.seek(512)
        header = self.handle.read(512)
        if header[:8] != b"EFI PART":
            raise ValueError("GPT header missing")
        table_lba, count, entry_size = struct.unpack_from("<QII", header, 72)
        if entry_size < 128 or count == 0 or count > 1024:
            raise ValueError("unsupported GPT table")
        self.handle.seek(table_lba * 512)
        for _ in range(count):
            entry = self.handle.read(entry_size)
            if len(entry) != entry_size:
                raise ValueError("truncated GPT table")
            if entry[:16] == b"\0" * 16:
                continue
            if uuid.UUID(bytes_le=entry[:16]) == ESP_TYPE:
                first, last = struct.unpack_from("<QQ", entry, 32)
                if first < 2 or last < first:
                    raise ValueError("invalid ESP extent")
                return first
        raise ValueError("EFI system partition missing")

    def _next_cluster(self, cluster: int) -> int | None:
        if self.fat_bits == 12:
            offset = cluster + cluster // 2
            if offset + 2 > len(self.fat):
                raise ValueError("truncated FAT12 table")
            packed = struct.unpack_from("<H", self.fat, offset)[0]
            value = packed >> 4 if cluster & 1 else packed & 0x0FFF
            return None if value >= 0x0FF8 else value
        if self.fat_bits == 16:
            offset = cluster * 2
            value = struct.unpack_from("<H", self.fat, offset)[0]
            return None if value >= 0xFFF8 else value
        offset = cluster * 4
        value = struct.unpack_from("<I", self.fat, offset)[0] & 0x0FFFFFFF
        return None if value >= 0x0FFFFFF8 else value

    def _cluster_data(self, cluster: int) -> bytes:
        if cluster < 2:
            raise ValueError("invalid FAT cluster")
        offset = self.data_offset + (cluster - 2) * self.cluster_bytes
        self.handle.seek(offset)
        data = self.handle.read(self.cluster_bytes)
        if len(data) != self.cluster_bytes:
            raise ValueError("truncated FAT cluster")
        return data

    def _chain(self, first: int):
        current = first
        seen: set[int] = set()
        while current is not None:
            if current in seen or len(seen) > 2_000_000:
                raise ValueError("invalid FAT cluster chain")
            seen.add(current)
            yield current
            current = self._next_cluster(current)

    @staticmethod
    def _lfn_piece(entry: bytes) -> str:
        raw = entry[1:11] + entry[14:26] + entry[28:32]
        chars: list[str] = []
        for index in range(0, len(raw), 2):
            value = struct.unpack_from("<H", raw, index)[0]
            if value in (0, 0xFFFF):
                break
            chars.append(chr(value))
        return "".join(chars)

    def _directory_bytes(self, cluster: int | None) -> bytes:
        if cluster is None and self.fat_bits != 32:
            size = self.root_entries * 32
            self.handle.seek(self.root_offset)
            return self.handle.read(size)
        first = self.root_cluster if cluster is None else cluster
        return b"".join(self._cluster_data(item) for item in self._chain(first))

    def entries(self, cluster: int | None) -> list[dict[str, object]]:
        data = self._directory_bytes(cluster)
        result: list[dict[str, object]] = []
        lfn: dict[int, str] = {}
        for offset in range(0, len(data), 32):
            entry = data[offset : offset + 32]
            if len(entry) < 32 or entry[0] == 0:
                break
            if entry[0] == 0xE5:
                lfn.clear()
                continue
            attributes = entry[11]
            if attributes == 0x0F:
                lfn[entry[0] & 0x1F] = self._lfn_piece(entry)
                continue
            if attributes & 0x08:
                lfn.clear()
                continue
            short_base = entry[:8].decode("ascii", errors="replace").rstrip()
            short_ext = entry[8:11].decode("ascii", errors="replace").rstrip()
            short = short_base + (f".{short_ext}" if short_ext else "")
            name = "".join(lfn[index] for index in sorted(lfn)) if lfn else short
            lfn.clear()
            high = struct.unpack_from("<H", entry, 20)[0]
            low = struct.unpack_from("<H", entry, 26)[0]
            result.append({
                "name": name,
                "cluster": (high << 16) | low,
                "bytes": struct.unpack_from("<I", entry, 28)[0],
                "directory": bool(attributes & 0x10),
            })
        return result

    def find(self, path: str) -> dict[str, object]:
        cluster: int | None = None
        parts = [part for part in path.replace("\\", "/").split("/") if part]
        for index, part in enumerate(parts):
            matches = [entry for entry in self.entries(cluster) if str(entry["name"]).casefold() == part.casefold()]
            if len(matches) != 1:
                raise ValueError(f"FAT path missing or ambiguous: {path}")
            match = matches[0]
            if index < len(parts) - 1:
                if not match["directory"]:
                    raise ValueError(f"FAT path component is not a directory: {part}")
                cluster = int(match["cluster"])
            else:
                return match
        raise ValueError("empty FAT path")

    def extract(self, path: str, output: Path) -> None:
        entry = self.find(path)
        if entry["directory"] or int(entry["cluster"]) < 2:
            raise ValueError("requested FAT path is not a regular file")
        if output.exists():
            raise ValueError(f"append-only collision: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        remaining = int(entry["bytes"])
        with output.open("xb") as target:
            for cluster in self._chain(int(entry["cluster"])):
                chunk = self._cluster_data(cluster)
                take = min(remaining, len(chunk))
                target.write(chunk[:take])
                remaining -= take
                if remaining == 0:
                    break
        if remaining != 0:
            raise ValueError("truncated FAT file")

    def hash_file(self, path: str) -> str:
        entry = self.find(path)
        if entry["directory"] or int(entry["cluster"]) < 2:
            raise ValueError("requested FAT path is not a regular file")
        remaining = int(entry["bytes"])
        digest = hashlib.sha256()
        for cluster in self._chain(int(entry["cluster"])):
            chunk = self._cluster_data(cluster)
            take = min(remaining, len(chunk))
            digest.update(chunk[:take])
            remaining -= take
            if remaining == 0:
                break
        if remaining != 0:
            raise ValueError("truncated FAT file")
        return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Casulo vendor UEFI bundle from sealed image")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--image-manifest", type=Path, required=True)
    parser.add_argument("--ramdisk-source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    manifest_path = args.image_manifest.resolve(strict=True)
    if ROOT.resolve() not in image.parents or ROOT.resolve() not in manifest_path.parents:
        raise SystemExit("image and manifest must remain inside repository")
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if _sha(image) != source_manifest.get("sha256"):
        raise SystemExit("sealed image hash mismatch")
    output = args.output.resolve()
    if ROOT.resolve() not in output.parents or output.exists():
        raise SystemExit("output must be a fresh repository directory")
    reader = FatImage(image)
    try:
        mapping = {
            "efi/boot/bootx64.efi": output / "EFI/Teloscorp/Casulo/CasuloX64.efi",
            "kernel-x86_64": output / "kernel-x86_64",
        }
        for source, target in mapping.items():
            reader.extract(source, target)
        ramdisk_target = output / "ramdisk"
        if args.ramdisk_source is None:
            reader.extract("ramdisk", ramdisk_target)
        else:
            ramdisk_source = args.ramdisk_source.resolve(strict=True)
            if ROOT.resolve() not in ramdisk_source.parents or not ramdisk_source.is_file():
                raise SystemExit("ramdisk source must be a repository file")
            if reader.hash_file("ramdisk") != _sha(ramdisk_source):
                raise SystemExit("image and content-addressed ramdisk source differ")
            ramdisk_target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(ramdisk_source, ramdisk_target)
            except OSError:
                shutil.copyfile(ramdisk_source, ramdisk_target)
    finally:
        reader.close()
    if (output / "EFI/Teloscorp/Casulo/CasuloX64.efi").read_bytes()[:2] != b"MZ":
        raise SystemExit("extracted EFI executable is not PE/COFF")
    if (output / "kernel-x86_64").read_bytes()[:4] != b"\x7fELF":
        raise SystemExit("extracted kernel is not ELF")
    if (output / "ramdisk").read_bytes()[:8] != b"CSPK0001":
        raise SystemExit("extracted ramdisk is not a Casulo system pack")
    files = {
        path.relative_to(output).as_posix(): {"bytes": path.stat().st_size, "sha256": _sha(path)}
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    record = {
        "schema": "casulo-uefi-coexistence-bundle/1.0",
        "source_image": image.relative_to(ROOT).as_posix(),
        "source_image_sha256": source_manifest["sha256"],
        "files": files,
        "existing_file_overwrites_required": False,
        "existing_file_deletes_required": False,
        "upstream_bootloader_root_abi": ["kernel-x86_64", "ramdisk"],
        "local_bundle_ramdisk_deduplicated": (
            args.ramdisk_source is not None
            and os.stat(output / "ramdisk").st_ino == os.stat(args.ramdisk_source.resolve()).st_ino
        ),
        "fallback_boot_path_touched_on_install": False,
        "physical_device_written": False,
    }
    output.joinpath("BUNDLE_MANIFEST.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
