"""Vercel Cron entry — sends the daily restock digest.

Scheduled in vercel.json (04:00 UTC = 08:00 UAE). Vercel calls GET /api/cron on
schedule. Alert channel + credentials come from environment variables.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler  # noqa: E402
import notify  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            _, message = notify.send_digest()
        except Exception as e:  # never 500 the cron; report the error text
            message = f"digest error: {e}"
        body = message.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
