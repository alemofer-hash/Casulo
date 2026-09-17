from __future__ import annotations
import argparse, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CREATION = json.loads((ROOT / "creation.json").read_text(encoding="utf-8"))
SIMULATION = json.loads((ROOT / "simulation-receipt.json").read_text(encoding="utf-8"))

class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload, content_type="application/json; charset=utf-8"):
        if isinstance(payload, str): body = payload.encode("utf-8")
        else: body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'none'; connect-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/": self._send(200, (ROOT / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
        elif self.path == "/health": self._send(200, {"ok": True, "effects": "simulation-only"})
        elif self.path == "/creation": self._send(200, CREATION)
        else: self._send(404, {"error": "not_found"})
    def do_POST(self):
        if self.path != "/simulate": self._send(404, {"error": "not_found"}); return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024: self._send(413, {"error": "body_too_large"}); return
        if length: self.rfile.read(length)
        self._send(200, SIMULATION)
    def log_message(self, *_args): return

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--port", type=int, default=8765); parser.add_argument("--once", action="store_true")
    args = parser.parse_args(); server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"bind": "127.0.0.1", "port": server.server_port}), flush=True)
    server.handle_request() if args.once else server.serve_forever()

if __name__ == "__main__": main()
