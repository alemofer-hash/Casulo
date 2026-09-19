"""Bound HTTP worker/socket pressure before allocating request body buffers."""
import threading
import ssl
from http.server import ThreadingHTTPServer


def discard_unread_body(handler, maximum_bytes):
    """Drain bounded rejected POST data before close to avoid Windows TCP RST.

    This discards bytes; it never parses, authorizes or logs their content.
    """
    if handler.command != "POST" or getattr(handler, "_body_consumed", False):
        return
    length = handler.headers.get("Content-Length", "")
    if not length.isdecimal() or not 0 < int(length) <= maximum_bytes:
        return
    previous = handler.connection.gettimeout()
    try:
        handler.connection.settimeout(2)
        handler.rfile.read(int(length))
        handler._body_consumed = True
    except OSError:
        pass
    finally:
        handler.connection.settimeout(previous)


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8
    defer_tls_handshake = True

    def __init__(self, *args, **kwargs):
        self._http_slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._http_slots.acquire(blocking=False):
            # No unbounded work queue. Closing before reading is deterministic
            # transport backpressure for unauthenticated connection pressure.
            self.shutdown_request(request)
            return
        request.settimeout(10)
        try:
            super().process_request(request, client_address)
        except Exception:
            self._http_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            if isinstance(request, ssl.SSLSocket):
                request.do_handshake()
            super().process_request_thread(request, client_address)
        except (OSError, ssl.SSLError):
            self.shutdown_request(request)
        finally:
            self._http_slots.release()
