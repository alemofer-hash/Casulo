from pathlib import Path


def test_usb_candidate_preflight_contains_no_destructive_disk_operation() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/inspect_native_usb_candidate.ps1").read_text(encoding="utf-8")
    for forbidden in (
        "Clear-Disk",
        "Initialize-Disk",
        "Format-Volume",
        "Remove-Partition",
        "Set-Partition",
        "diskpart",
        "PhysicalDrive",
    ):
        assert forbidden not in source
    assert "Get-Disk" in source
    assert "physical_device_written = $false" in source
