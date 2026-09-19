"""Cleo endpoints on the existing authenticated Family Gateway only."""
import base64
import ipaddress
from http import HTTPStatus
from urllib.parse import urlsplit

from .contracts import (FamilyAuthorizationError, FamilyBackpressureError,
                        FamilyUnavailableError)
from .gateway import FamilyGateway, PWA_FILES
from .persona import PrincipalBinding
from .bounded_http import BoundedThreadingHTTPServer

PWA_FILES["/voice.js"] = ("voice.js", "text/javascript; charset=utf-8")


class CleoGateway(FamilyGateway):
    def __init__(self, *, voice, **kwargs):
        self.voice = voice
        super().__init__(server_class=BoundedThreadingHTTPServer, **kwargs)
        if self.security is None:
            raise FamilyAuthorizationError("Cleo requires device authentication")

    def _session(self, handler):
        session = super()._session(handler)
        binding = self.voice.resolver.authorize(session.auth)
        if binding.local_host and not ipaddress.ip_address(handler.client_address[0]).is_loopback:
            raise FamilyAuthorizationError("PERSONA_DENIED")
        return session

    def _voice_error(self, handler, error):
        status = 401 if isinstance(error, FamilyAuthorizationError) else (
            429 if isinstance(error, FamilyBackpressureError) else (
                503 if isinstance(error, FamilyUnavailableError) else 400))
        self._json(handler, HTTPStatus(status), {"error": type(error).__name__},
                   headers={"Retry-After": "1"} if status == 429 else None)

    def _handle_post(self, handler):
        path = urlsplit(handler.path).path
        if path != "/v1/admin/host-session" and not path.startswith("/v1/voice"):
            return super()._handle_post(handler)
        if not self._client_allowed(handler):
            return self._json(handler, HTTPStatus.FORBIDDEN, {"error": "NETWORK_DENIED"})
        try:
            if path == "/v1/admin/host-session":
                self._require_owner(handler)
                if not ipaddress.ip_address(handler.client_address[0]).is_loopback:
                    raise FamilyAuthorizationError("PERSONA_DENIED")
                self._require_same_origin(handler)
                payload = self._read_json(handler)
                if payload != {"output_route": "LOCAL_PRIVATE", "sole_participant": True}:
                    raise FamilyAuthorizationError("PERSONA_DENIED")
                if not self.voice.resolver._unlocked():
                    raise FamilyAuthorizationError("PERSONA_DENIED")
                code = self.security.issue_pairing_code("guilherme", role="owner")
                session = self.security.pair(code.code, "Cleo host local", source="127.0.0.1")
                self.voice.resolver.bind(PrincipalBinding(
                    session.auth, "guilherme", local_host=True, route="LOCAL_PRIVATE"))
                return self._json(handler, HTTPStatus.CREATED, {"status": "HOST_BOUND"},
                                  cookies=session.set_cookie_headers(
                                      max_age_seconds=self.security.session_ttl_seconds))
            # Cancellation is allowed to the authenticated owner even after lock
            # or route downgrade, but never to another session.
            session = FamilyGateway._session(self, handler)
            self._require_same_origin(handler)
            self.security.verify_csrf(session, handler.headers.get("X-Casulo-CSRF"))
            auth = session.auth
            payload = self._read_json(handler)
            if path == "/v1/voice":
                self._auth(handler)
                if set(payload) != {"wav_base64"} or not isinstance(payload["wav_base64"], str):
                    raise ValueError("audio only")
                audio = base64.b64decode(payload["wav_base64"], validate=True)
                turn = self.voice.submit(auth, audio)
                return self._json(handler, HTTPStatus.ACCEPTED, {"turn_id": turn})
            if path == "/v1/voice/private-route-lost":
                if payload:
                    raise ValueError("empty body required")
                self.voice.resolver.downgrade(auth)
                return self._json(handler, HTTPStatus.OK, {"status": "DENIED_UNTIL_LOCAL_REBIND"})
            parts = path.split("/")
            if len(parts) == 5 and set(payload) == set():
                if parts[4] == "cancel":
                    self.voice.cancel(auth, parts[3])
                elif parts[4] == "finished":
                    self.voice.playback_finished(auth, parts[3])
                else:
                    raise ValueError("unknown voice action")
                return self._json(handler, HTTPStatus.OK, {"accepted": True})
            raise ValueError("unknown voice route")
        except Exception as error:
            self._voice_error(handler, error)

    def _handle_get(self, handler):
        path = urlsplit(handler.path).path
        if not path.startswith("/v1/voice/"):
            return super()._handle_get(handler)
        try:
            if not self._client_allowed(handler):
                raise FamilyAuthorizationError("NETWORK_DENIED")
            auth = self._auth(handler)
            parts = path.split("/")
            if len(parts) == 4:
                return self._json(handler, HTTPStatus.OK, self.voice.snapshot(auth, parts[3]))
            if len(parts) == 5 and parts[4] == "audio":
                raw = self.voice.take_audio(auth, parts[3])
                handler.send_response(200)
                handler.send_header("Content-Type", "audio/wav")
                handler.send_header("Content-Length", str(len(raw)))
                handler.send_header("Cache-Control", "no-store")
                self._security_headers(handler)
                handler.end_headers()
                try:
                    handler.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    self.voice.cancel(auth, parts[3])
                return
            raise ValueError("unknown voice route")
        except Exception as error:
            self._voice_error(handler, error)

    def _security_headers(self, handler):
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
        handler.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                            "style-src 'self'; connect-src 'self'; media-src 'self' blob:; "
                            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if self.config.tls_certfile:
            handler.send_header("Strict-Transport-Security", "max-age=31536000")
