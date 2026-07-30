"""Lightweight passcode auth with signed session cookies (stdlib only).

Two roles: 'admin' (the EA) and 'staff' (Eddie & Danilo). A passcode maps to a
role; on success we hand back a cookie value that is HMAC-signed with a local
secret, so no server-side session store is needed and logins survive restarts.
"""

import hmac
import hashlib
import os
import time
import base64

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("RESTOCK_DATA_DIR") or HERE
SECRET_PATH = os.path.join(DATA_DIR, ".secret")

SESSION_DAYS = 30
COOKIE_NAME = "restock_session"


def _secret():
    if not os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "wb") as f:
            f.write(os.urandom(32))
        os.chmod(SECRET_PATH, 0o600)
    with open(SECRET_PATH, "rb") as f:
        return f.read()


def role_for_passcode(passcode, cfg):
    passcode = (passcode or "").strip()
    if not passcode:
        return None
    if passcode == cfg.get("admin_passcode"):
        return "admin"
    if passcode == cfg.get("staff_passcode"):
        return "staff"
    return None


def make_cookie(role):
    expiry = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{role}:{expiry}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def read_cookie(cookie_value):
    """Return the role if the cookie is valid and unexpired, else None."""
    if not cookie_value:
        return None
    try:
        raw = base64.urlsafe_b64decode(cookie_value.encode()).decode()
        role, expiry, sig = raw.rsplit(":", 2)
    except Exception:
        return None
    payload = f"{role}:{expiry}"
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if int(expiry) < int(time.time()):
        return None
    if role not in ("admin", "staff"):
        return None
    return role


def parse_cookie_header(header):
    """Pull our session cookie out of a raw Cookie: header."""
    if not header:
        return None
    for part in header.split(";"):
        if "=" in part:
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                return value
    return None
