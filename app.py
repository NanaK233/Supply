"""Restock site — self-contained HTTP server (Python standard library only).

Run:   python3 app.py
Then open http://localhost:8765 in your browser.

Two roles, chosen by passcode at login:
  admin  — the EA: full control (edit schedule, delete, approve suggestions, alerts)
  staff  — Eddie & Danilo: see stock, add items, update stock, flag low, restock
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import store
import notify
import auth
import sync
import scheduler

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
PORT = int(os.environ.get("PORT") or os.environ.get("RESTOCK_PORT") or "8765")


class Handler(BaseHTTPRequestHandler):
    # --- helpers -----------------------------------------------------------
    def _json(self, obj, status=200, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _role(self):
        cookie = auth.parse_cookie_header(self.headers.get("Cookie"))
        return auth.read_cookie(cookie)

    def _require(self, *allowed):
        """Return the caller's role if allowed, else send 401/403 and None."""
        role = self._role()
        if role is None:
            self._json({"error": "Not signed in"}, 401)
            return None
        if allowed and role not in allowed:
            self._json({"error": "Not allowed for your role"}, 403)
            return None
        return role

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ctypes = {".html": "text/html", ".css": "text/css",
                  ".js": "application/javascript", ".svg": "image/svg+xml"}
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctypes.get(ext, "text/plain"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass

    # --- GET ---------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/me":
            role = self._role()
            return self._json({"role": role})

        if path == "/api/items":
            if self._require() is None:
                return
            return self._json({"items": store.list_items(),
                               "owners": store.OWNERS})

        if path == "/api/summary":
            if self._require() is None:
                return
            return self._json(notify.build_digest())

        if path == "/api/notify/preview":
            if self._require("admin") is None:
                return
            cfg = notify.load_config()
            digest = notify.build_digest()
            return self._json({
                "text": notify.render_text(digest),
                "channels": cfg.get("channels", []),
                "email_ready": notify.email_ready(cfg),
                "whatsapp_ready": notify.whatsapp_ready(cfg),
            })

        m = re.match(r"^/api/items/(\d+)/history$", path)
        if m:
            if self._require("admin") is None:
                return
            return self._json({"history": store.history(int(m.group(1)))})

        return self._serve_static(path)

    # --- POST --------------------------------------------------------------
    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/login":
            cfg = notify.load_config()
            role = auth.role_for_passcode(self._body().get("passcode"), cfg)
            if role is None:
                return self._json({"error": "Wrong passcode"}, 401)
            cookie = (f"{auth.COOKIE_NAME}={auth.make_cookie(role)}; "
                      f"Path=/; HttpOnly; SameSite=Lax; Max-Age={auth.SESSION_DAYS*86400}")
            return self._json({"role": role}, cookie=cookie)

        if path == "/api/logout":
            cookie = f"{auth.COOKIE_NAME}=; Path=/; HttpOnly; Max-Age=0"
            return self._json({"ok": True}, cookie=cookie)

        if path == "/api/items":  # add item — staff + admin
            if self._require("admin", "staff") is None:
                return
            data = self._body()
            if not data.get("name", "").strip():
                return self._json({"error": "Name is required"}, 400)
            return self._json(store.create_item(data), 201)

        # stock-level update — staff + admin
        m = re.match(r"^/api/items/(\d+)/quantity$", path)
        if m:
            if self._require("admin", "staff") is None:
                return
            b = self._body()
            result = store.update_quantity(int(m.group(1)), b.get("quantity", ""),
                                           b.get("unit"))
            if result is None:
                return self._json({"error": "Not found"}, 404)
            return self._json(result)

        # restock / flag-low — staff + admin
        m = re.match(r"^/api/items/(\d+)/(restock|flag-low)$", path)
        if m:
            if self._require("admin", "staff") is None:
                return
            fn = {"restock": store.mark_restocked, "flag-low": store.flag_low}[m.group(2)]
            result = fn(int(m.group(1)))
            if result is None:
                return self._json({"error": "Not found"}, 404)
            return self._json(result)

        # apply / dismiss suggestion — admin only
        m = re.match(r"^/api/items/(\d+)/(apply-suggestion|dismiss-suggestion)$", path)
        if m:
            if self._require("admin") is None:
                return
            fn = {"apply-suggestion": store.apply_suggestion,
                  "dismiss-suggestion": store.dismiss_suggestion}[m.group(2)]
            result = fn(int(m.group(1)))
            if result is None:
                return self._json({"error": "Not found or not applicable"}, 404)
            return self._json(result)

        if path == "/api/notify/send":  # admin only
            if self._require("admin") is None:
                return
            sent, message = notify.send_digest(force=self._body().get("force", False))
            return self._json({"sent": sent, "message": message})

        return self._json({"error": "Unknown endpoint"}, 404)

    # --- PUT (admin only) --------------------------------------------------
    def do_PUT(self):
        m = re.match(r"^/api/items/(\d+)$", self.path.split("?")[0])
        if m:
            if self._require("admin") is None:
                return
            result = store.update_item(int(m.group(1)), self._body())
            if result is None:
                return self._json({"error": "Not found"}, 404)
            return self._json(result)
        return self._json({"error": "Unknown endpoint"}, 404)

    # --- DELETE (admin only) ----------------------------------------------
    def do_DELETE(self):
        m = re.match(r"^/api/items/(\d+)$", self.path.split("?")[0])
        if m:
            if self._require("admin") is None:
                return
            store.delete_item(int(m.group(1)))
            return self._json({"ok": True})
        return self._json({"error": "Unknown endpoint"}, 404)


def main():
    store.init_db()
    sync.start_if_enabled()
    scheduler.start_if_enabled()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Restock site running →  http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
