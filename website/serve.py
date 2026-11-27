#!/usr/bin/env python3
"""Local preview of website/dist: serves the static build (directory indexes, 404 page) and forwards
/api/public/* to the Permit360 application, so the live committee lookup and the form work in preview.

    python website/serve.py [--port 8790] [--app https://permit360.kortexd.com]"""
import argparse
import http.server
import urllib.error
import urllib.request
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist"


def handler(app: str):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(DIST), **k)

        def _proxy(self, method: str):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else None
            req = urllib.request.Request(app + self.path, data=body, method=method,
                                         headers={"Content-Type": self.headers.get("Content-Type", "application/json"), "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    code, data = r.status, r.read()
            except urllib.error.HTTPError as e:
                code, data = e.code, e.read()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/api/public/"):
                return self._proxy("GET")
            path = DIST / self.path.split("?")[0].lstrip("/")
            if not path.exists() and not (path / "index.html").exists():
                data = (DIST / "site" / "404.html").read_bytes()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            return super().do_GET()

        def do_POST(self):
            if self.path.startswith("/api/public/"):
                return self._proxy("POST")
            self.send_error(405)

        def guess_type(self, path):
            t = super().guess_type(path)
            return t + "; charset=utf-8" if t.startswith(("text/", "application/javascript", "application/json")) else t
    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--app", default="https://permit360.kortexd.com")
    a = ap.parse_args()
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler(a.app.rstrip("/"))).serve_forever()
