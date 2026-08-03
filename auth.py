"""Lightweight name-based auth with signed session cookies (stdlib only).

People sign in by picking their name from a list (configured under "users" in
config.json). Each name maps to a role: 'admin' (Nana Kofi) or 'staff' (Eddie,
Danilo). The cookie carries the name + role, HMAC-signed with a local secret,
so no server-side session store is needed and logins survive restarts.
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
_SEP = "|"  # names never contain this


def _secret():
    # On a serverless host (e.g. Vercel) the filesystem is ephemeral, so use a
    # stable secret from the environment. Locally, fall back to a generated file.
    env = os.environ.get("RESTOCK_SECRET")
    if env:
        return env.encode()
    if not os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "wb") as f:
            f.write(os.urandom(32))
        os.chmod(SECRET_PATH, 0o600)
    with open(SECRET_PATH, "rb") as f:
        return f.read()


def users(cfg):
    return cfg.get("users") or []


def role_for_name(name, cfg):
    """Return the role for a login name, or None if it isn't a known user."""
    name = (name or "").strip()
    for u in users(cfg):
        if u.get("name") == name:
            return u.get("role")
    return None


def make_cookie(role, name):
    expiry = int(time.time()) + SESSION_DAYS * 86400
    payload = _SEP.join((role, name, str(expiry)))
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    raw = _SEP.join((payload, sig))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def read_cookie(cookie_value):
    """Return {'role', 'name'} if the cookie is valid and unexpired, else None."""
    if not cookie_value:
        return None
    try:
        raw = base64.urlsafe_b64decode(cookie_value.encode()).decode()
        role, name, expiry, sig = raw.split(_SEP)
    except Exception:
        return None
    payload = _SEP.join((role, name, expiry))
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if int(expiry) < int(time.time()):
        return None
    if role not in ("admin", "staff"):
        return None
    return {"role": role, "name": name}


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
