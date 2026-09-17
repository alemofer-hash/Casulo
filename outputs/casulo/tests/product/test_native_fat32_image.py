from pathlib import Path

from tools.build_casulo_uefi_image import Fat32Writer
from tools.extract_casulo_uefi_bundle import FatImage


def test_first_party_fat32_writer_roundtrips_boot_files(tmp_path: Path) -> None:
    bootloader = tmp_path / "bootx64.efi"
    kernel = tmp_path / "kernel"
    ramdisk = tmp_path / "pack"
    bootloader.write_bytes(b"MZ" + b"efi")
    kernel.write_bytes(b"\x7fELFkernel")
    ramdisk.write_bytes(b"CSPK0001pack")
    image = tmp_path / "casulo.img"
    Fat32Writer(image, {"bootx64": bootloader, "kernel": kernel, "ramdisk": ramdisk}).build()

    reader = FatImage(image)
    try:
        for source, expected in (
            ("efi/boot/bootx64.efi", bootloader),
            ("kernel-x86_64", kernel),
            ("ramdisk", ramdisk),
        ):
            target = tmp_path / (source.replace("/", "-") + ".out")
            reader.extract(source, target)
            assert target.read_bytes() == expected.read_bytes()
    finally:
        reader.close()
