from __future__ import annotations
import argparse, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({"ok": True, "bind": "loopback", "effects": "simulation-only"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
    def log_message(self, *_): pass
def main():
    p=argparse.ArgumentParser(); p.add_argument("--port", type=int, default=0); a=p.parse_args()
    s=ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(json.dumps({"bind":"127.0.0.1","port":s.server_port}), flush=True); s.serve_forever()
if __name__ == "__main__": main()
