#!/usr/bin/env python3
"""conflictwatch static server — serves web/ + /data/snapshot.json (no-store)."""
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
PORT = int(os.environ.get("CONFLICTWATCH_PORT", 8220))

ALLOWED_DATA = {"snapshot.json"}

class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def do_GET(self):
        path = urlparse(self.path).path  # strip ?ts= cache-buster
        if path.startswith("/data/"):
            name = os.path.basename(path)
            if name not in ALLOWED_DATA:
                self.send_error(404); return
            f = os.path.join(HERE, "data", name)
            if not os.path.exists(f):
                self.send_error(503, "snapshot not ready"); return
            with open(f, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.path = path
        super().do_GET()

    def log_message(self, fmt, *args):
        pass

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
