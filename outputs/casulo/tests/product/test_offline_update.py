from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from casulo.product.offline_update import LABEL, OfflineABUpdater, OfflineUpdateError


def package(root: Path, *, version: str = "1.0.0", payload: bytes = b"candidate", valid: bool = True) -> Path:
    root.mkdir()
    (root / "payload.bin").write_bytes(payload)
    manifest = {
        "schema": "casulo.offline-update/1.0", "version": version,
        "channel": "owner-offline-development", "from_versions": ["0.0.0"],
        "payload_sha256": hashlib.sha256(payload).hexdigest(), "rollback_floor": "0.0.0",
        "signature_class": LABEL,
    }
    (root / "UPDATE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "UPDATE_MANIFEST.json.sig").write_bytes(b"valid" if valid else b"invalid")
    return root


def verifier(_manifest: Path, signature: Path) -> bool:
    return signature.read_bytes() == b"valid"


def test_valid_update_switches_slot_and_keeps_rollback(tmp_path) -> None:
    updater = OfflineABUpdater(tmp_path / "runtime", signature_verifier=verifier)
    receipt = updater.apply(package(tmp_path / "package"), health_check=lambda slot: (slot / "payload.bin").read_bytes() == b"candidate")
    assert receipt.installed_version == "1.0.0" and receipt.slot == "B"
    assert receipt.signature_verified and receipt.rollback_available
    assert updater.current_state()["version"] == "1.0.0"


@pytest.mark.parametrize("mutation", ["signature", "payload", "downgrade"])
def test_invalid_update_is_rejected_without_switch(tmp_path, mutation) -> None:
    updater = OfflineABUpdater(tmp_path / "runtime", signature_verifier=verifier)
    source = package(tmp_path / "package", version="0.0.0" if mutation == "downgrade" else "1.0.0", valid=mutation != "signature")
    if mutation == "payload":
        (source / "payload.bin").write_bytes(b"tampered")
    with pytest.raises(OfflineUpdateError):
        updater.apply(source, health_check=lambda _slot: True)
    assert updater.current_state()["version"] == "0.0.0"


def test_failed_health_preserves_current_slot(tmp_path) -> None:
    updater = OfflineABUpdater(tmp_path / "runtime", signature_verifier=verifier)
    with pytest.raises(OfflineUpdateError, match="health"):
        updater.apply(package(tmp_path / "package"), health_check=lambda _slot: False)
    assert updater.current_state()["slot"] == "A"
