# TEMP DEBUG — echo the path + headers Vercel passes, to fix routing.
from http.server import BaseHTTPRequestHandler
import json

class handler(BaseHTTPRequestHandler):
    def _dump(self):
        info = {"path": self.path, "headers": {k: v for k, v in self.headers.items()}}
        body = json.dumps(info, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self): self._dump()
    def do_POST(self): self._dump()
