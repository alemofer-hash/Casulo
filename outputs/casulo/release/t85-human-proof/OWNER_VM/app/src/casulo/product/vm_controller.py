from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .platform_contracts import PlatformError


class VMControllerError(PlatformError):
    pass


_SNAPSHOT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_device_path(path: str | Path) -> None:
    raw = os.fspath(path)
    normalized = raw.replace("\\", "/").lower()
    _drive, tail = os.path.splitdrive(raw)
    if (
        "physicaldrive" in normalized
        or normalized.startswith("//./")
        or normalized.startswith("//?/")
        or normalized.startswith("/dev/")
        or ":" in tail
    ):
        raise VMControllerError("block device fisico ou alternate data stream e proibido")


def _linklike(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _regular(path: str | Path, *, label: str) -> Path:
    _reject_device_path(path)
    candidate = Path(path).expanduser()
    if _linklike(candidate):
        raise VMControllerError(f"{label} nao pode ser symlink ou junction")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise VMControllerError(f"{label} precisa ser arquivo regular")
    return resolved


def _confined(root: Path, path: str | Path, *, label: str, must_exist: bool = False) -> Path:
    _reject_device_path(path)
    candidate = Path(path).expanduser()
    if _linklike(candidate):
        raise VMControllerError(f"{label} nao pode ser symlink ou junction")
    resolved = candidate.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise VMControllerError(f"{label} escapou da raiz da VM") from error
    return resolved


@dataclass(frozen=True, slots=True)
class VMProfile:
    qemu: Path
    qemu_img: Path
    ovmf_code: Path
    ovmf_vars_template: Path
    base_image: Path
    state_root: Path
    memory_mb: int = 4096
    vcpus: int = 4
    overlay_quota_gib: int = 12

    def __post_init__(self) -> None:
        for name in ("qemu", "qemu_img", "ovmf_code", "ovmf_vars_template", "base_image"):
            object.__setattr__(self, name, _regular(getattr(self, name), label=name))
        root_candidate = Path(self.state_root).expanduser()
        _reject_device_path(root_candidate)
        if _linklike(root_candidate):
            raise VMControllerError("state_root nao pode ser symlink ou junction")
        root = root_candidate.resolve(strict=False)
        if not 512 <= self.memory_mb <= 12 * 1024 or not 1 <= self.vcpus <= 8:
            raise VMControllerError("recursos da VM fora do envelope")
        if not 1 <= self.overlay_quota_gib <= 16:
            raise VMControllerError("quota de overlay fora do envelope")
        object.__setattr__(self, "state_root", root)


class CasuloVMController:
    def __init__(self, profile: VMProfile) -> None:
        self.profile = profile

    @property
    def manifest_path(self) -> Path:
        return self.profile.state_root / "vm-manifest.json"

    @property
    def overlay_path(self) -> Path:
        return self.profile.state_root / "owner-overlay.qcow2"

    @property
    def vars_path(self) -> Path:
        return self.profile.state_root / "OVMF_VARS.fd"

    def doctor(self) -> dict[str, Any]:
        qemu_version = self._version(self.profile.qemu, "--version")
        image_version = self._version(self.profile.qemu_img, "--version")
        accelerators = self._capture([str(self.profile.qemu), "-accel", "help"])
        free = shutil.disk_usage(self.profile.state_root.parent).free
        overlay = self.overlay_path
        report = {
            "schema": "casulo.vm-doctor/1.0",
            "read_only": True,
            "qemu": str(self.profile.qemu),
            "qemu_sha256": _sha256(self.profile.qemu),
            "qemu_version": qemu_version,
            "qemu_img_version": image_version,
            "accelerators": [name for name in ("whpx", "tcg") if name in accelerators.lower()],
            "selected_acceleration": "whpx" if "whpx" in accelerators.lower() else "tcg",
            "ovmf_code": str(self.profile.ovmf_code),
            "ovmf_code_sha256": _sha256(self.profile.ovmf_code),
            "base_image": str(self.profile.base_image),
            "base_image_sha256": _sha256(self.profile.base_image),
            "base_os_read_only": not os.access(self.profile.base_image, os.W_OK),
            "state_root": str(self.profile.state_root),
            "overlay_exists": overlay.is_file() and not overlay.is_symlink(),
            "free_bytes": free,
            "minimum_reserve_bytes": 20 * 1024**3,
            "reserve_pass": free - self.profile.overlay_quota_gib * 1024**3 >= 20 * 1024**3,
            "network": "denied",
            "shared_folder": False,
            "clipboard": False,
            "host_block_devices": False,
            "external_media": "NOT_IN_USE",
            "cloud": "RELEASE_LOCKED",
        }
        report["ready"] = bool(
            report["reserve_pass"]
            and report["accelerators"]
            and self.profile.base_image.is_file()
            and report["base_os_read_only"]
        )
        return report

    def create(self) -> dict[str, Any]:
        doctor = self.doctor()
        if not doctor["ready"]:
            raise VMControllerError("doctor da VM reprovou")
        root = self.profile.state_root
        if root.exists() and any(root.iterdir()):
            raise VMControllerError("state_root nao esta vazio; overwrite negado")
        root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.profile.ovmf_vars_template, self.vars_path)
        command = [
            str(self.profile.qemu_img), "create", "-f", "qcow2", "-F", "raw",
            "-b", str(self.profile.base_image), str(self.overlay_path),
            f"{self.profile.overlay_quota_gib}G",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
        if completed.returncode != 0:
            raise VMControllerError(f"qemu-img create falhou: {completed.stderr[-2000:]}")
        manifest = {
            "schema": "casulo.vm-profile/1.0",
            "machine": "q35",
            "base_image": str(self.profile.base_image),
            "base_sha256": _sha256(self.profile.base_image),
            "base_read_only": True,
            "overlay": str(self.overlay_path),
            "overlay_format": "qcow2",
            "overlay_quota_gib": self.profile.overlay_quota_gib,
            "ovmf_vars": str(self.vars_path),
            "network": "denied",
            "qmp": "tcp-loopback-ephemeral-only",
            "physical_devices": False,
            "external_media": "NOT_IN_USE",
            "cloud": "RELEASE_LOCKED",
        }
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return manifest

    def build_argv(
        self,
        *,
        acceleration: str,
        paused: bool = False,
        serial_client_port: int | None = None,
        serial_server_port: int | None = None,
    ) -> list[str]:
        if acceleration not in {"whpx", "tcg"}:
            raise VMControllerError("aceleracao fora da allowlist")
        _confined(self.profile.state_root, self.overlay_path, label="overlay", must_exist=True)
        _confined(self.profile.state_root, self.vars_path, label="OVMF vars", must_exist=True)
        serial_argv = ["-serial", "stdio"]
        if serial_client_port is not None and serial_server_port is not None:
            raise VMControllerError("modo serial ambiguo")
        serial_port = serial_server_port if serial_server_port is not None else serial_client_port
        if serial_port is not None:
            if not 1 <= serial_port <= 65535:
                raise VMControllerError("porta serial loopback invalida")
            server_options = ",server=on,wait=on" if serial_server_port is not None else ",server=off"
            serial_argv = [
                "-chardev",
                f"socket,id=ownerbridge,host=127.0.0.1,port={serial_port}{server_options},nodelay=on",
                "-serial",
                "chardev:ownerbridge",
            ]
        argv = [
            str(self.profile.qemu),
            "-machine", f"q35,accel={acceleration}",
            "-m", f"{self.profile.memory_mb}M",
            "-smp", str(self.profile.vcpus),
            "-nodefaults", "-display", "none", *serial_argv, "-monitor", "none",
            "-nic", "none", "-no-reboot",
            "-qmp", "tcp:127.0.0.1:0,server=on,wait=off",
            "-device", "VGA",
            "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={self.profile.ovmf_code}",
            "-drive", f"if=pflash,format=raw,unit=1,file={self.vars_path}",
            "-drive", f"if=none,id=casulo,format=qcow2,file={self.overlay_path}",
            "-device", "virtio-blk-pci,drive=casulo",
            "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
        ]
        if paused:
            argv.append("-S")
        return argv

    def boot(self, *, timeout: float = 30.0) -> dict[str, Any]:
        before = _sha256(self.profile.base_image)
        doctor = self.doctor()
        selected = str(doctor["selected_acceleration"])
        result = self._run_boot(selected, timeout)
        if not result["passed"] and selected == "whpx" and "tcg" in doctor["accelerators"]:
            result = self._run_boot("tcg", timeout)
            result["fallback_from"] = "whpx"
        after = _sha256(self.profile.base_image)
        result["base_sha256_before"] = before
        result["base_sha256_after"] = after
        result["base_unchanged"] = before == after
        return result

    def bridge_boot(
        self,
        response: str | Callable[[], str],
        *,
        timeout: float = 900.0,
        acceleration: str | None = None,
    ) -> dict[str, Any]:
        """Boot the owner profile and answer one bounded guest request."""
        cached: list[bytes] = []

        def provide() -> bytes:
            if cached:
                return cached[0]
            value = response() if callable(response) else response
            if not isinstance(value, str):
                raise VMControllerError("provider da ponte nao retornou texto")
            encoded = value.encode("utf-8")
            if not encoded or len(encoded) > 4096 or b"\n" in encoded or b"\r" in encoded:
                raise VMControllerError("resposta da ponte precisa ser uma linha UTF-8 de 1..4096 bytes")
            cached.append(encoded)
            return encoded

        if not callable(response):
            provide()  # reject invalid static data before starting QEMU
        before = _sha256(self.profile.base_image)
        doctor = self.doctor()
        if acceleration is not None and acceleration not in doctor["accelerators"]:
            raise VMControllerError("aceleracao solicitada indisponivel")
        selected = acceleration or str(doctor["selected_acceleration"])
        result = self._run_bridge(selected, provide, timeout)
        if (
            acceleration is None
            and not result["passed"]
            and selected == "whpx"
            and "tcg" in doctor["accelerators"]
        ):
            result = self._run_bridge("tcg", provide, timeout)
            result["fallback_from"] = "whpx"
        result["base_sha256_before"] = before
        result["base_sha256_after"] = _sha256(self.profile.base_image)
        result["base_unchanged"] = result["base_sha256_before"] == result["base_sha256_after"]
        return result

    def preloaded_bridge_boot(
        self,
        response: str,
        *,
        timeout: float = 120.0,
        acceleration: str = "tcg",
    ) -> dict[str, Any]:
        """Deliver a bounded response before guest receive begins.

        This is the deterministic reboot handoff for the current Native
        profile: a prior guest boot submits the job, the owner worker persists
        its result, and the next boot consumes that result from the same scoped
        UART. It is intentionally not represented as live token streaming.
        """
        encoded = response.encode("utf-8")
        if not encoded or len(encoded) > 4096 or b"\n" in encoded or b"\r" in encoded:
            raise VMControllerError("resposta preloaded precisa ser uma linha UTF-8 de 1..4096 bytes")
        doctor = self.doctor()
        if acceleration not in doctor["accelerators"]:
            raise VMControllerError("aceleracao solicitada indisponivel")
        before = _sha256(self.profile.base_image)
        result = self._run_preloaded_bridge(acceleration, encoded, timeout)
        result["base_sha256_before"] = before
        result["base_sha256_after"] = _sha256(self.profile.base_image)
        result["base_unchanged"] = result["base_sha256_before"] == result["base_sha256_after"]
        return result

    def _run_preloaded_bridge(
        self,
        acceleration: str,
        response: bytes,
        timeout: float,
    ) -> dict[str, Any]:
        reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
        reservation.close()
        process = subprocess.Popen(
            self.build_argv(acceleration=acceleration, serial_server_port=port),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        connection: socket.socket | None = None
        serial = bytearray()
        timed_out = False
        live_serial_path = self.profile.state_root / "bridge-preloaded-live.serial.bin"
        try:
            connect_deadline = time.monotonic() + min(timeout, 30.0)
            while connection is None and time.monotonic() < connect_deadline:
                try:
                    connection = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                except OSError:
                    if process.poll() is not None:
                        break
                    time.sleep(0.05)
            if connection is None:
                raise VMControllerError("serial preloaded indisponivel")
            connection.settimeout(0.25)
            # QEMU owns the socket before firmware starts, so the chardev can
            # buffer the line until COM1 is initialized by Casulo Native.
            for byte in response + b"\n":
                connection.sendall(bytes((byte,)))
                time.sleep(0.002)
            deadline = time.monotonic() + timeout
            with live_serial_path.open("wb") as live_serial:
                while time.monotonic() < deadline:
                    try:
                        chunk = connection.recv(4096)
                    except ConnectionResetError:
                        break
                    except socket.timeout:
                        if process.poll() is not None:
                            break
                        continue
                    if not chunk:
                        break
                    serial.extend(chunk)
                    live_serial.write(chunk)
                    live_serial.flush()
                else:
                    timed_out = True
        finally:
            if connection is not None:
                connection.close()
        if timed_out and process.poll() is None:
            process.kill()
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait(timeout=5)
        output = serial.decode("utf-8", "replace")
        return {
            "acceleration": acceleration,
            "returncode": returncode,
            "timed_out": timed_out,
            "response_bytes": len(response),
            "response_sha256": hashlib.sha256(response).hexdigest(),
            "serial": output,
            "serial_sha256": hashlib.sha256(bytes(serial)).hexdigest(),
            "live_serial_path": str(live_serial_path),
            "passed": (
                returncode == 33
                and "OWNER_GENERATIVE_BRIDGE=PASS" in output
                and f"OWNER_ENGINE_RESPONSE_RECEIVED_BYTES={len(response)}" in output
            ),
            "network": "denied",
            "host_block_devices": False,
            "delivery_mode": "PRELOADED_REBOOT_HANDOFF",
            "request_seen": "OWNER_BRIDGE_REQUEST=resume-owner-creation" in output,
        }

    def _run_bridge(
        self,
        acceleration: str,
        response_provider: Callable[[], bytes],
        timeout: float,
    ) -> dict[str, Any]:
        # The controller listens first and QEMU connects as a loopback client,
        # avoiding a guest-facing or externally reachable server. This remains
        # a one-request UART capability, not a generic tunnel.
        reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
        reservation.close()
        process = subprocess.Popen(
            self.build_argv(acceleration=acceleration, serial_server_port=port),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        serial = bytearray()
        sent = False
        response_bytes = 0
        response_sha256: str | None = None
        bridge_ready_monotonic_ns: int | None = None
        provider_started_monotonic_ns: int | None = None
        provider_ended_monotonic_ns: int | None = None
        timed_out = False
        provider_error: Exception | None = None
        connection: socket.socket | None = None
        live_serial_path = self.profile.state_root / "bridge-live.serial.bin"
        try:
            connect_deadline = time.monotonic() + min(timeout, 30.0)
            while connection is None and time.monotonic() < connect_deadline:
                try:
                    connection = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                except OSError:
                    if process.poll() is not None:
                        break
                    time.sleep(0.05)
            if connection is None:
                raise socket.timeout("QEMU serial loopback server unavailable")
            connection.settimeout(0.25)
            deadline = time.monotonic() + timeout
            with live_serial_path.open("wb") as live_serial:
                while time.monotonic() < deadline:
                    try:
                        chunk = connection.recv(4096)
                    except ConnectionResetError:
                        break
                    except socket.timeout:
                        if process.poll() is not None:
                            break
                        continue
                    if not chunk:
                        break
                    serial.extend(chunk)
                    live_serial.write(chunk)
                    live_serial.flush()
                    if not sent and b"OWNER_BRIDGE_READY=1" in serial:
                        bridge_ready_monotonic_ns = time.monotonic_ns()
                        provider_started_monotonic_ns = time.monotonic_ns()
                        response = response_provider()
                        response_sha256 = hashlib.sha256(response).hexdigest()
                        # Pace bytes for the emulated 16550 FIFO. A single
                        # sendall can overrun guest receive state on Windows
                        # WHPX/TCG even though the TCP write succeeds.
                        for byte in response + b"\n":
                            connection.sendall(bytes((byte,)))
                            time.sleep(0.002)
                        response_bytes = len(response)
                        provider_ended_monotonic_ns = time.monotonic_ns()
                        sent = True
                else:
                    timed_out = True
        except (OSError, socket.timeout):
            timed_out = True
        except Exception as error:
            provider_error = error
        finally:
            if connection is not None:
                connection.close()
        if (timed_out or provider_error is not None) and process.poll() is None:
            process.kill()
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait(timeout=5)
        if provider_error is not None:
            raise VMControllerError("provider da ponte falhou; guest encerrado") from provider_error
        output = serial.decode("utf-8", "replace")
        return {
            "acceleration": acceleration,
            "returncode": returncode,
            "timed_out": timed_out,
            "request_seen": "OWNER_BRIDGE_REQUEST=resume-owner-creation" in output,
            "response_sent": sent,
            "response_bytes": response_bytes,
            "response_sha256": response_sha256,
            "bridge_ready_monotonic_ns": bridge_ready_monotonic_ns,
            "provider_started_monotonic_ns": provider_started_monotonic_ns,
            "provider_ended_monotonic_ns": provider_ended_monotonic_ns,
            "serial": output,
            "serial_sha256": hashlib.sha256(bytes(serial)).hexdigest(),
            "live_serial_path": str(live_serial_path),
            "passed": (
                returncode == 33
                and sent
                and "OWNER_GENERATIVE_BRIDGE=PASS" in output
                and f"OWNER_ENGINE_RESPONSE_RECEIVED_BYTES={response_bytes}" in output
            ),
            "network": "denied",
            "host_block_devices": False,
        }

    def _run_boot(self, acceleration: str, timeout: float) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                self.build_argv(acceleration=acceleration),
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = completed.stdout
            timed_out = False
            returncode = completed.returncode
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            output = partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial
            timed_out, returncode = True, -1
        return {
            "acceleration": acceleration,
            "returncode": returncode,
            "timed_out": timed_out,
            "serial": output,
            "serial_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "passed": returncode == 33 and "G1_BOOT_SMOKE=PASS" in output,
            "network": "denied",
            "host_block_devices": False,
        }

    def snapshot(self, name: str) -> dict[str, Any]:
        if not _SNAPSHOT.fullmatch(name):
            raise VMControllerError("nome de snapshot invalido")
        if self.snapshot_exists(name):
            return {
                "snapshot": name,
                "overlay_sha256": _sha256(self.overlay_path),
                "created": False,
                "idempotent": True,
            }
        self._qemu_img("snapshot", "-c", name, str(self.overlay_path))
        return {
            "snapshot": name,
            "overlay_sha256": _sha256(self.overlay_path),
            "created": True,
            "idempotent": False,
        }

    def snapshots(self) -> tuple[str, ...]:
        """List internal QCOW2 snapshots without mutating the overlay."""
        output = self._capture([str(self.profile.qemu_img), "snapshot", "-l", str(self.overlay_path)])
        found: list[str] = []
        for line in output.splitlines():
            columns = line.split()
            if len(columns) >= 2 and columns[0].isdigit() and _SNAPSHOT.fullmatch(columns[1]):
                found.append(columns[1])
        return tuple(found)

    def snapshot_exists(self, name: str) -> bool:
        if not _SNAPSHOT.fullmatch(name):
            raise VMControllerError("nome de snapshot invalido")
        return name in self.snapshots()

    def restore(self, name: str) -> dict[str, Any]:
        if not _SNAPSHOT.fullmatch(name):
            raise VMControllerError("nome de snapshot invalido")
        if not self.snapshot_exists(name):
            raise VMControllerError(f"snapshot inexistente: {name}; execute :snapshot antes de :restore")
        self._qemu_img("snapshot", "-a", name, str(self.overlay_path))
        return {"restored": name, "base_sha256": _sha256(self.profile.base_image)}

    def reset_to_snapshot(self, name: str) -> dict[str, Any]:
        """Recoverably reset owner overlay to an explicitly named snapshot."""
        before = _sha256(self.profile.base_image)
        restored = self.restore(name)
        return {
            "reset_to": restored["restored"],
            "base_sha256_before": before,
            "base_sha256_after": _sha256(self.profile.base_image),
            "feedback_paths_touched": False,
        }

    def crash_recovery_probe(self) -> dict[str, Any]:
        base_before = _sha256(self.profile.base_image)
        process = subprocess.Popen(
            self.build_argv(acceleration="tcg", paused=True),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        process.kill()
        process.wait(timeout=5)
        check = subprocess.run(
            [str(self.profile.qemu_img), "check", str(self.overlay_path)],
            capture_output=True, text=True, encoding="utf-8", check=False
        )
        return {
            "process_terminated": process.returncode is not None,
            "overlay_check_returncode": check.returncode,
            "overlay_check_output": (check.stdout + check.stderr)[-2000:],
            "base_unchanged": base_before == _sha256(self.profile.base_image),
        }

    def _qemu_img(self, *arguments: str) -> None:
        try:
            completed = subprocess.run(
                [str(self.profile.qemu_img), *arguments], capture_output=True,
                text=True, encoding="utf-8", errors="replace", check=False,
                shell=False,
            )
        except OSError as error:
            raise VMControllerError(f"qemu-img indisponivel: {type(error).__name__}") from error
        if completed.returncode != 0:
            raise VMControllerError(f"qemu-img falhou: {(completed.stdout + completed.stderr)[-2000:]}")

    @staticmethod
    def _capture(command: list[str]) -> str:
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False, shell=False,
            )
        except OSError as error:
            raise VMControllerError(f"dependencia da VM indisponivel: {type(error).__name__}") from error
        if completed.returncode != 0:
            raise VMControllerError("dependencia da VM nao respondeu")
        return completed.stdout + completed.stderr

    def _version(self, executable: Path, argument: str) -> str:
        return self._capture([str(executable), argument]).splitlines()[0]
