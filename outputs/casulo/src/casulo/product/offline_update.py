from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .platform_contracts import PlatformError


LABEL = "DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE"
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class OfflineUpdateError(PlatformError):
    pass


@dataclass(frozen=True, slots=True)
class UpdateReceipt:
    previous_version: str
    installed_version: str
    slot: str
    payload_sha256: str
    signature_verified: bool
    health_passed: bool
    rollback_available: bool

    def to_dict(self) -> dict[str, object]:
        return {"schema": "casulo.offline-update-receipt/1.0", **{name: getattr(self, name) for name in self.__slots__}}


def verify_ssh_signature(manifest: Path, signature: Path, allowed_signers: Path, identity: str) -> bool:
    if not all(path.is_file() and not path.is_symlink() for path in (manifest, signature, allowed_signers)):
        return False
    result = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(allowed_signers), "-I", identity, "-n", "casulo-update", "-s", str(signature)],
        input=manifest.read_bytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, check=False, timeout=15,
    )
    return result.returncode == 0


class OfflineABUpdater:
    """Fail-closed A/B updater; it never executes payload or migration code."""

    def __init__(self, root: str | Path, *, signature_verifier: Callable[[Path, Path], bool]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.signature_verifier = signature_verifier
        self.root.mkdir(parents=True, exist_ok=True)

    def apply(self, package: str | Path, *, health_check: Callable[[Path], bool]) -> UpdateReceipt:
        source = Path(package).expanduser().resolve(strict=True)
        manifest_path = source / "UPDATE_MANIFEST.json"
        signature_path = source / "UPDATE_MANIFEST.json.sig"
        payload_path = source / "payload.bin"
        if source.is_symlink() or not source.is_dir() or set(item.name for item in source.iterdir()) != {manifest_path.name, signature_path.name, payload_path.name}:
            raise OfflineUpdateError("layout de update inválido")
        if any(path.is_symlink() or not path.is_file() for path in (manifest_path, signature_path, payload_path)):
            raise OfflineUpdateError("update exige arquivos regulares")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise OfflineUpdateError("manifesto de update inválido") from error
        expected = {"schema", "version", "channel", "from_versions", "payload_sha256", "rollback_floor", "signature_class"}
        if not isinstance(manifest, dict) or set(manifest) != expected or manifest.get("schema") != "casulo.offline-update/1.0":
            raise OfflineUpdateError("contrato de update inválido")
        version = self._version(manifest["version"])
        rollback_floor = self._version(manifest["rollback_floor"])
        if manifest["channel"] != "owner-offline-development" or manifest["signature_class"] != LABEL:
            raise OfflineUpdateError("canal ou classe de assinatura inválidos")
        if not isinstance(manifest["from_versions"], list) or not manifest["from_versions"]:
            raise OfflineUpdateError("from_versions inválido")
        current = self.current_state()
        current_version = str(current["version"])
        if current_version not in manifest["from_versions"] or version <= self._version(current_version) or version < rollback_floor:
            raise OfflineUpdateError("downgrade ou origem não autorizada")
        if hashlib.sha256(payload_path.read_bytes()).hexdigest() != manifest["payload_sha256"]:
            raise OfflineUpdateError("payload hash divergente")
        if not self.signature_verifier(manifest_path, signature_path):
            raise OfflineUpdateError("assinatura de update inválida")
        inactive = "B" if current["slot"] == "A" else "A"
        destination = (self.root / f"slot-{inactive}").resolve()
        staging = (self.root / f".slot-{inactive}.{os.getpid()}.staging").resolve()
        for candidate in (destination, staging):
            try:
                candidate.relative_to(self.root)
            except ValueError as error:
                raise OfflineUpdateError("slot escapou da raiz") from error
        if staging.exists():
            raise OfflineUpdateError("staging de update já existe")
        staging.mkdir()
        try:
            copied = staging / "payload.bin"
            shutil.copyfile(payload_path, copied)
            if hashlib.sha256(copied.read_bytes()).hexdigest() != manifest["payload_sha256"]:
                raise OfflineUpdateError("bytes staged divergiram")
            if not health_check(staging):
                raise OfflineUpdateError("health do slot candidato falhou")
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(staging, destination)
            state = {"schema": "casulo.offline-update-state/1.0", "slot": inactive, "version": manifest["version"], "previous_slot": current["slot"], "previous_version": current_version}
            temporary = self.root / f".CURRENT.{os.getpid()}.tmp"
            temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            os.replace(temporary, self.root / "CURRENT.json")
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return UpdateReceipt(current_version, manifest["version"], inactive, manifest["payload_sha256"], True, True, (self.root / f"slot-{current['slot']}").is_dir())

    def current_state(self) -> dict[str, str]:
        path = self.root / "CURRENT.json"
        if not path.exists():
            initial = {"schema": "casulo.offline-update-state/1.0", "slot": "A", "version": "0.0.0", "previous_slot": "A", "previous_version": "0.0.0"}
            slot = self.root / "slot-A"
            slot.mkdir(exist_ok=True)
            path.write_text(json.dumps(initial, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            return initial
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise OfflineUpdateError("estado CURRENT inválido") from error
        if not isinstance(value, dict) or value.get("schema") != "casulo.offline-update-state/1.0" or value.get("slot") not in {"A", "B"}:
            raise OfflineUpdateError("estado CURRENT incompatível")
        self._version(value.get("version"))
        return value

    @staticmethod
    def _version(value: object) -> tuple[int, int, int]:
        if not isinstance(value, str) or not (match := _VERSION.fullmatch(value)):
            raise OfflineUpdateError("versão semântica inválida")
        return tuple(int(item) for item in match.groups())
