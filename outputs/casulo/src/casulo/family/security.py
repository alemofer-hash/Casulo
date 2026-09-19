from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path

from .contracts import (
    AuthContext,
    FamilyAuthorizationError,
    FamilyContractError,
    _validate_identifier,
)


DEVICE_COOKIE = "casulo_device"
SESSION_COOKIE = "casulo_session"
CSRF_COOKIE = "casulo_csrf"
PAIRING_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _digest(salt: bytes, secret: str) -> str:
    return hashlib.sha256(salt + secret.encode("ascii")).hexdigest()


def _token_parts(value: str, label: str) -> tuple[str, str]:
    identifier, separator, secret = value.partition(".")
    if not separator or len(secret) < 32:
        raise FamilyAuthorizationError(f"cookie {label} inválido")
    try:
        _validate_identifier(identifier, label)
    except FamilyContractError as error:
        raise FamilyAuthorizationError(f"cookie {label} inválido") from error
    return identifier, secret


@dataclass(frozen=True, slots=True)
class PairingCode:
    code: str
    user_id: str
    role: str
    expires_utc: str


@dataclass(frozen=True, slots=True)
class PairedSession:
    auth: AuthContext
    role: str
    device_cookie: str
    session_cookie: str
    csrf_token: str

    def set_cookie_headers(self, *, max_age_seconds: int) -> tuple[str, ...]:
        common = f"Path=/; Max-Age={max_age_seconds}; Secure; SameSite=Strict"
        return (
            f"{DEVICE_COOKIE}={self.device_cookie}; {common}; HttpOnly",
            f"{SESSION_COOKIE}={self.session_cookie}; {common}; HttpOnly",
            f"{CSRF_COOKIE}={self.csrf_token}; {common}",
        )


class DeviceRegistry:
    """Durable device/session authority; raw credentials are never persisted."""

    def __init__(
        self,
        path: Path,
        *,
        pairing_ttl_seconds: int = 300,
        session_ttl_seconds: int = 30 * 24 * 60 * 60,
        max_pair_attempts: int = 5,
    ) -> None:
        if not 30 <= pairing_ttl_seconds <= 300:
            raise ValueError("pairing TTL deve ficar entre 30 e 300 segundos")
        if not 300 <= session_ttl_seconds <= 90 * 24 * 60 * 60:
            raise ValueError("session TTL fora do limite")
        if not 1 <= max_pair_attempts <= 20:
            raise ValueError("limite de tentativas inválido")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.pairing_ttl_seconds = pairing_ttl_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self.max_pair_attempts = max_pair_attempts
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, timeout=5, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._attempts: dict[str, list[float]] = {}
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    salt BLOB NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    expires_utc TEXT NOT NULL,
                    consumed_utc TEXT
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    credential_hash TEXT NOT NULL,
                    salt BLOB NOT NULL,
                    created_utc TEXT NOT NULL,
                    revoked_utc TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES devices(device_id),
                    user_id TEXT NOT NULL,
                    credential_hash TEXT NOT NULL,
                    credential_salt BLOB NOT NULL,
                    csrf_hash TEXT NOT NULL,
                    csrf_salt BLOB NOT NULL,
                    created_utc TEXT NOT NULL,
                    expires_utc TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL,
                    revoked_utc TEXT
                );
                CREATE INDEX IF NOT EXISTS sessions_device
                    ON sessions(device_id, revoked_utc);
                """
            )

    def issue_pairing_code(self, user_id: str, *, role: str = "family") -> PairingCode:
        _validate_identifier(user_id, "user_id")
        if role not in {"owner", "family", "restricted", "guest"}:
            raise FamilyContractError("role inválida")
        now = _utc_now()
        expires = now + timedelta(seconds=self.pairing_ttl_seconds)
        for _ in range(8):
            code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(10))
            salt = secrets.token_bytes(16)
            code_hash = _digest(salt, code)
            try:
                with self._lock, self._connection:
                    self._connection.execute(
                        """INSERT INTO pairing_codes
                        (code_hash, salt, user_id, role, created_utc, expires_utc)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (code_hash, salt, user_id, role, _iso(now), _iso(expires)),
                    )
                return PairingCode(code, user_id, role, _iso(expires))
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("não foi possível gerar código único")

    def pair(self, code: str, display_name: str, *, source: str) -> PairedSession:
        self._record_pair_attempt(source)
        normalized = code.strip().upper()
        if len(normalized) != 10 or any(ch not in PAIRING_ALPHABET for ch in normalized):
            raise FamilyAuthorizationError("código de pareamento inválido")
        name = display_name.strip()
        if not 1 <= len(name) <= 80 or any(ord(ch) < 32 for ch in name):
            raise FamilyContractError("nome de dispositivo inválido")
        now = _utc_now()
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM pairing_codes WHERE consumed_utc IS NULL"
            ).fetchall()
            match = next(
                (
                    row
                    for row in rows
                    if hmac.compare_digest(
                        row["code_hash"], _digest(bytes(row["salt"]), normalized)
                    )
                ),
                None,
            )
            if match is None or _parse_utc(match["expires_utc"]) < now:
                raise FamilyAuthorizationError("código inválido ou expirado")
            device_id = "dev-" + uuid.uuid4().hex
            device_secret = secrets.token_urlsafe(32)
            device_salt = secrets.token_bytes(16)
            with self._connection:
                updated = self._connection.execute(
                    """UPDATE pairing_codes SET consumed_utc = ?
                    WHERE code_hash = ? AND consumed_utc IS NULL""",
                    (_iso(now), match["code_hash"]),
                ).rowcount
                if updated != 1:
                    raise FamilyAuthorizationError("código já utilizado")
                self._connection.execute(
                    """INSERT INTO devices
                    (device_id, user_id, role, display_name, credential_hash,
                     salt, created_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        device_id,
                        match["user_id"],
                        match["role"],
                        name,
                        _digest(device_salt, device_secret),
                        device_salt,
                        _iso(now),
                    ),
                )
            return self._new_session(
                device_id=device_id,
                device_secret=device_secret,
                user_id=match["user_id"],
                role=match["role"],
            )

    def authenticate(self, cookie_header: str | None) -> PairedSession:
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header or "")
            device_value = cookies[DEVICE_COOKIE].value
            session_value = cookies[SESSION_COOKIE].value
            csrf_value = cookies[CSRF_COOKIE].value
        except (KeyError, ValueError) as error:
            raise FamilyAuthorizationError("cookies de sessão ausentes") from error
        device_id, device_secret = _token_parts(device_value, "device")
        session_id, session_secret = _token_parts(session_value, "session")
        now = _utc_now()
        with self._lock:
            row = self._connection.execute(
                """SELECT s.*, d.role, d.credential_hash AS device_hash,
                          d.salt AS device_salt, d.revoked_utc AS device_revoked
                FROM sessions s JOIN devices d ON d.device_id = s.device_id
                WHERE s.session_id = ? AND s.device_id = ?""",
                (session_id, device_id),
            ).fetchone()
            if row is None:
                raise FamilyAuthorizationError("sessão desconhecida")
            valid = (
                row["revoked_utc"] is None
                and row["device_revoked"] is None
                and _parse_utc(row["expires_utc"]) >= now
                and hmac.compare_digest(
                    row["device_hash"],
                    _digest(bytes(row["device_salt"]), device_secret),
                )
                and hmac.compare_digest(
                    row["credential_hash"],
                    _digest(bytes(row["credential_salt"]), session_secret),
                )
                and hmac.compare_digest(
                    row["csrf_hash"], _digest(bytes(row["csrf_salt"]), csrf_value)
                )
            )
            if not valid:
                raise FamilyAuthorizationError("credencial revogada ou inválida")
            with self._connection:
                self._connection.execute(
                    "UPDATE sessions SET last_seen_utc = ? WHERE session_id = ?",
                    (_iso(now), session_id),
                )
        return PairedSession(
            auth=AuthContext(row["user_id"], device_id, session_id),
            role=row["role"],
            device_cookie=device_value,
            session_cookie=session_value,
            csrf_token=csrf_value,
        )

    def verify_csrf(self, session: PairedSession, header: str | None) -> None:
        if not header or not hmac.compare_digest(session.csrf_token, header):
            raise FamilyAuthorizationError("CSRF inválido")

    def revoke_device(self, device_id: str) -> int:
        _validate_identifier(device_id, "device_id")
        now = _iso(_utc_now())
        with self._lock, self._connection:
            updated = self._connection.execute(
                """UPDATE devices SET revoked_utc = ?
                WHERE device_id = ? AND revoked_utc IS NULL""",
                (now, device_id),
            ).rowcount
            if updated != 1:
                raise KeyError(device_id)
            sessions = self._connection.execute(
                """UPDATE sessions SET revoked_utc = ?
                WHERE device_id = ? AND revoked_utc IS NULL""",
                (now, device_id),
            ).rowcount
        return int(sessions)

    def revoke_session(self, auth: AuthContext) -> bool:
        now = _iso(_utc_now())
        with self._lock, self._connection:
            updated = self._connection.execute(
                """UPDATE sessions SET revoked_utc = ?
                WHERE session_id = ? AND device_id = ? AND user_id = ?
                  AND revoked_utc IS NULL""",
                (now, auth.session_id, auth.device_id, auth.user_id),
            ).rowcount
        return updated == 1

    def is_context_active(self, auth: AuthContext) -> bool:
        with self._lock:
            row = self._connection.execute(
                """SELECT s.expires_utc, s.revoked_utc, d.revoked_utc device_revoked
                FROM sessions s JOIN devices d ON d.device_id = s.device_id
                WHERE s.session_id = ? AND s.device_id = ? AND s.user_id = ?""",
                (auth.session_id, auth.device_id, auth.user_id),
            ).fetchone()
        return bool(
            row
            and row["revoked_utc"] is None
            and row["device_revoked"] is None
            and _parse_utc(row["expires_utc"]) >= _utc_now()
        )

    def diagnostics(self) -> dict[str, int]:
        with self._lock:
            devices = self._connection.execute(
                "SELECT COUNT(*) FROM devices WHERE revoked_utc IS NULL"
            ).fetchone()[0]
            sessions = self._connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE revoked_utc IS NULL"
            ).fetchone()[0]
        return {"active_devices": int(devices), "active_sessions": int(sessions)}

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _new_session(
        self, *, device_id: str, device_secret: str, user_id: str, role: str
    ) -> PairedSession:
        now = _utc_now()
        expires = now + timedelta(seconds=self.session_ttl_seconds)
        session_id = "ses-" + uuid.uuid4().hex
        session_secret = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session_salt = secrets.token_bytes(16)
        csrf_salt = secrets.token_bytes(16)
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO sessions
                (session_id, device_id, user_id, credential_hash, credential_salt,
                 csrf_hash, csrf_salt, created_utc, expires_utc, last_seen_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    device_id,
                    user_id,
                    _digest(session_salt, session_secret),
                    session_salt,
                    _digest(csrf_salt, csrf_token),
                    csrf_salt,
                    _iso(now),
                    _iso(expires),
                    _iso(now),
                ),
            )
        return PairedSession(
            auth=AuthContext(user_id, device_id, session_id),
            role=role,
            device_cookie=f"{device_id}.{device_secret}",
            session_cookie=f"{session_id}.{session_secret}",
            csrf_token=csrf_token,
        )

    def _record_pair_attempt(self, source: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [value for value in self._attempts.get(source, []) if now - value < 300]
            if len(recent) >= self.max_pair_attempts:
                raise FamilyAuthorizationError("tentativas de pareamento excedidas")
            recent.append(now)
            self._attempts[source] = recent
