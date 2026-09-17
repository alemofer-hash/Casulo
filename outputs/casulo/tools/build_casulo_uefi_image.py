#!/usr/bin/env python3
"""Build a deterministic GPT/FAT32 Casulo image with correct large-file slack."""

from __future__ import annotations

import argparse
import math
import struct
import sys
import uuid
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.extract_casulo_uefi_bundle import FatImage  # noqa: E402


SECTOR = 512
ESP_TYPE = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
DISK_GUID = uuid.UUID("6e17d646-a0e8-4ed3-b7b8-8d707a6ebd11")
PARTITION_GUID = uuid.UUID("bd32a68f-75f3-47f9-b10c-9130a7c0f8cd")


def _short_entry(name: bytes, attributes: int, cluster: int, size: int = 0) -> bytes:
    if len(name) != 11:
        raise ValueError("FAT short name must contain eleven bytes")
    entry = bytearray(32)
    entry[:11] = name
    entry[11] = attributes
    struct.pack_into("<H", entry, 20, (cluster >> 16) & 0xFFFF)
    struct.pack_into("<H", entry, 26, cluster & 0xFFFF)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


def _lfn_checksum(short: bytes) -> int:
    value = 0
    for byte in short:
        value = ((value & 1) << 7) + (value >> 1) + byte
        value &= 0xFF
    return value


def _lfn_entries(name: str, short: bytes) -> list[bytes]:
    units = list(name.encode("utf-16le"))
    words = [units[index] | units[index + 1] << 8 for index in range(0, len(units), 2)]
    if len(words) % 13:
        words.append(0)
    while len(words) % 13:
        words.append(0xFFFF)
    chunks = [words[index : index + 13] for index in range(0, len(words), 13)]
    result: list[bytes] = []
    checksum = _lfn_checksum(short)
    for sequence in range(len(chunks), 0, -1):
        entry = bytearray(b"\xff" * 32)
        entry[0] = sequence | (0x40 if sequence == len(chunks) else 0)
        entry[11] = 0x0F
        entry[12] = 0
        entry[13] = checksum
        entry[26:28] = b"\0\0"
        chunk = chunks[sequence - 1]
        positions = (1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30)
        for position, word in zip(positions, chunk, strict=True):
            struct.pack_into("<H", entry, position, word)
        result.append(bytes(entry))
    return result


class Fat32Writer:
    def __init__(self, output: Path, files: dict[str, Path]) -> None:
        self.output = output
        self.files = files
        payload_bytes = sum(path.stat().st_size for path in files.values())
        self.sectors_per_cluster = 64 if payload_bytes >= 512 * 1024 * 1024 else 1
        self.cluster_bytes = SECTOR * self.sectors_per_cluster
        self.file_clusters = {
            name: math.ceil(path.stat().st_size / self.cluster_bytes) for name, path in files.items()
        }
        required = 3 + sum(self.file_clusters.values())
        # Keep FAT32 classification even for tiny test fixtures and reserve a
        # bounded 1% growth margin for directory/metadata evolution.
        self.cluster_count = max(65_525, required + max(128, math.ceil(required * 0.01)))
        self.reserved = 32
        self.fats = 2
        self.fat_sectors = math.ceil((self.cluster_count + 2) * 4 / SECTOR)
        self.first_data_sector = self.reserved + self.fats * self.fat_sectors
        self.partition_sectors = self.first_data_sector + self.cluster_count * self.sectors_per_cluster
        self.partition_lba = 2048
        self.partition_last_lba = self.partition_lba + self.partition_sectors - 1
        self.disk_last_lba = self.partition_last_lba + 33
        self.partition_offset = self.partition_lba * SECTOR
        self.data_offset = self.partition_offset + self.first_data_sector * SECTOR
        self.chains: dict[str, list[int]] = {}
        cursor = 5
        for name in ("bootx64", "kernel", "ramdisk"):
            count = self.file_clusters[name]
            self.chains[name] = list(range(cursor, cursor + count))
            cursor += count
        self.allocated_clusters = cursor - 2

    def _cluster_offset(self, cluster: int) -> int:
        return self.data_offset + (cluster - 2) * self.cluster_bytes

    def _boot_sector(self) -> bytes:
        boot = bytearray(512)
        boot[:3] = b"\xeb\x58\x90"
        boot[3:11] = b"CASULO  "
        struct.pack_into("<H", boot, 11, SECTOR)
        boot[13] = self.sectors_per_cluster
        struct.pack_into("<H", boot, 14, self.reserved)
        boot[16] = self.fats
        struct.pack_into("<H", boot, 17, 0)
        struct.pack_into("<H", boot, 19, 0)
        boot[21] = 0xF8
        struct.pack_into("<H", boot, 22, 0)
        struct.pack_into("<H", boot, 24, 63)
        struct.pack_into("<H", boot, 26, 255)
        struct.pack_into("<I", boot, 28, self.partition_lba)
        struct.pack_into("<I", boot, 32, self.partition_sectors)
        struct.pack_into("<I", boot, 36, self.fat_sectors)
        struct.pack_into("<H", boot, 40, 0)
        struct.pack_into("<H", boot, 42, 0)
        struct.pack_into("<I", boot, 44, 2)
        struct.pack_into("<H", boot, 48, 1)
        struct.pack_into("<H", boot, 50, 6)
        boot[64] = 0x80
        boot[66] = 0x29
        struct.pack_into("<I", boot, 67, 0x43415355)
        boot[71:82] = b"CASULO OS  "
        boot[82:90] = b"FAT32   "
        boot[510:512] = b"\x55\xaa"
        return bytes(boot)

    def _fsinfo(self) -> bytes:
        info = bytearray(512)
        struct.pack_into("<I", info, 0, 0x41615252)
        struct.pack_into("<I", info, 484, 0x61417272)
        struct.pack_into("<I", info, 488, self.cluster_count - self.allocated_clusters)
        struct.pack_into("<I", info, 492, self.allocated_clusters + 2)
        struct.pack_into("<I", info, 508, 0xAA550000)
        return bytes(info)

    def _fat(self) -> bytes:
        values = [0] * (self.cluster_count + 2)
        values[0] = 0x0FFFFFF8
        values[1] = 0x0FFFFFFF
        values[2] = values[3] = values[4] = 0x0FFFFFFF
        for chain in self.chains.values():
            for current, following in zip(chain, chain[1:]):
                values[current] = following
            values[chain[-1]] = 0x0FFFFFFF
        raw = bytearray(self.fat_sectors * SECTOR)
        for index, value in enumerate(values):
            struct.pack_into("<I", raw, index * 4, value)
        return bytes(raw)

    def _directories(self) -> dict[int, bytes]:
        root = bytearray(self.cluster_bytes)
        entries: list[bytes] = [_short_entry(b"EFI        ", 0x10, 3)]
        kernel_short = b"KERNEL~1   "
        entries.extend(_lfn_entries("kernel-x86_64", kernel_short))
        entries.append(
            _short_entry(kernel_short, 0x20, self.chains["kernel"][0], self.files["kernel"].stat().st_size)
        )
        entries.append(
            _short_entry(b"RAMDISK    ", 0x20, self.chains["ramdisk"][0], self.files["ramdisk"].stat().st_size)
        )
        for index, entry in enumerate(entries):
            root[index * 32 : (index + 1) * 32] = entry

        efi = bytearray(self.cluster_bytes)
        efi_entries = (
            _short_entry(b".          ", 0x10, 3),
            _short_entry(b"..         ", 0x10, 2),
            _short_entry(b"BOOT       ", 0x10, 4),
        )
        for index, entry in enumerate(efi_entries):
            efi[index * 32 : (index + 1) * 32] = entry

        boot = bytearray(self.cluster_bytes)
        boot_entries = (
            _short_entry(b".          ", 0x10, 4),
            _short_entry(b"..         ", 0x10, 3),
            _short_entry(
                b"BOOTX64 EFI",
                0x20,
                self.chains["bootx64"][0],
                self.files["bootx64"].stat().st_size,
            ),
        )
        for index, entry in enumerate(boot_entries):
            boot[index * 32 : (index + 1) * 32] = entry
        return {2: bytes(root), 3: bytes(efi), 4: bytes(boot)}

    def _gpt_entries(self) -> bytes:
        entries = bytearray(128 * 128)
        entries[:16] = ESP_TYPE.bytes_le
        entries[16:32] = PARTITION_GUID.bytes_le
        struct.pack_into("<QQQ", entries, 32, self.partition_lba, self.partition_last_lba, 0)
        name = "Casulo Boot".encode("utf-16le")
        entries[56 : 56 + len(name)] = name
        return bytes(entries)

    def _gpt_header(self, current: int, backup: int, entries_lba: int, entries_crc: int) -> bytes:
        header = bytearray(512)
        header[:8] = b"EFI PART"
        struct.pack_into("<I", header, 8, 0x00010000)
        struct.pack_into("<I", header, 12, 92)
        struct.pack_into("<QQQQ", header, 24, current, backup, 34, self.partition_last_lba)
        header[56:72] = DISK_GUID.bytes_le
        struct.pack_into("<QIII", header, 72, entries_lba, 128, 128, entries_crc)
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]) & 0xFFFFFFFF)
        return bytes(header)

    def build(self) -> None:
        if self.output.exists():
            raise ValueError(f"append-only collision: {self.output}")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with self.output.open("xb") as target:
            target.truncate((self.disk_last_lba + 1) * SECTOR)
            mbr = bytearray(512)
            mbr[446:462] = struct.pack(
                "<B3sB3sII", 0, b"\0\x02\0", 0xEE, b"\xff\xff\xff", 1, min(self.disk_last_lba, 0xFFFFFFFF)
            )
            mbr[510:512] = b"\x55\xaa"
            target.seek(0)
            target.write(mbr)
            entries = self._gpt_entries()
            entries_crc = zlib.crc32(entries) & 0xFFFFFFFF
            target.seek(SECTOR)
            target.write(self._gpt_header(1, self.disk_last_lba, 2, entries_crc))
            target.seek(2 * SECTOR)
            target.write(entries)
            backup_entries_lba = self.disk_last_lba - 32
            target.seek(backup_entries_lba * SECTOR)
            target.write(entries)
            target.seek(self.disk_last_lba * SECTOR)
            target.write(self._gpt_header(self.disk_last_lba, 1, backup_entries_lba, entries_crc))

            boot = self._boot_sector()
            info = self._fsinfo()
            target.seek(self.partition_offset)
            target.write(boot)
            target.seek(self.partition_offset + SECTOR)
            target.write(info)
            target.seek(self.partition_offset + 6 * SECTOR)
            target.write(boot)
            target.seek(self.partition_offset + 7 * SECTOR)
            target.write(info)
            fat = self._fat()
            for copy in range(self.fats):
                target.seek(self.partition_offset + (self.reserved + copy * self.fat_sectors) * SECTOR)
                target.write(fat)
            for cluster, data in self._directories().items():
                target.seek(self._cluster_offset(cluster))
                target.write(data)
            for name, source in self.files.items():
                remaining = source.stat().st_size
                with source.open("rb") as handle:
                    for cluster in self.chains[name]:
                        chunk = handle.read(min(self.cluster_bytes, remaining))
                        if not chunk and remaining:
                            raise ValueError(f"source truncated during copy: {name}")
                        target.seek(self._cluster_offset(cluster))
                        target.write(chunk)
                        remaining -= len(chunk)
                if remaining != 0:
                    raise ValueError(f"source length mismatch: {name}")
            target.flush()


def extract_bootloader(image: Path, output: Path) -> None:
    reader = FatImage(image)
    try:
        reader.extract("efi/boot/bootx64.efi", output)
    finally:
        reader.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Casulo GPT/FAT32 UEFI image")
    parser.add_argument("--bootloader", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--ramdisk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = {
        "bootx64": args.bootloader.resolve(strict=True),
        "kernel": args.kernel.resolve(strict=True),
        "ramdisk": args.ramdisk.resolve(strict=True),
    }
    Fat32Writer(args.output.resolve(), files).build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
