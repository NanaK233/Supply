import os, sys, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http.server import BaseHTTPRequestHandler

try:
    from app import Handler as _AppHandler
    _IMPORT_ERR = None
except Exception:
    _AppHandler = None
    _IMPORT_ERR = traceback.format_exc()

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if _IMPORT_ERR:
            body = ("IMPORT_ERROR\n" + _IMPORT_ERR).encode()
            self.send_response(500)
        else:
            body = ("IMPORT_OK Handler=%r" % _AppHandler).encode()
            self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self): self.do_GET()
