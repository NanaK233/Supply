"""Notification engine: builds the restock digest and (optionally) emails it.

Sending uses Python's built-in smtplib — no external service SDK required.
Configure by copying config.example.json to config.json and filling it in,
OR by setting the equivalent environment variables. If nothing is configured,
the digest is still generated (and printed / shown in the UI) but not emailed.
"""

import base64
import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage

import store

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    cfg = {
        "admin_passcode": "boss-1234",
        "staff_passcode": "team-5678",
        "channels": ["email"],
        "smtp_host": os.environ.get("RESTOCK_SMTP_HOST", ""),
        "smtp_port": int(os.environ.get("RESTOCK_SMTP_PORT", "587")),
        "smtp_user": os.environ.get("RESTOCK_SMTP_USER", ""),
        "smtp_password": os.environ.get("RESTOCK_SMTP_PASSWORD", ""),
        "from_addr": os.environ.get("RESTOCK_FROM", ""),
        "recipients": [],
        "whatsapp": {},
        "lead_days": store.DEFAULT_LEAD_DAYS,
    }
    # Environment variables (used in the cloud, e.g. GitHub Actions Secrets).
    # These fill in when there's no config.json; config.json wins locally.
    if os.environ.get("RESTOCK_CHANNELS"):
        cfg["channels"] = os.environ["RESTOCK_CHANNELS"]
    for env_key, cfg_key in (("RESTOCK_ADMIN_PASSCODE", "admin_passcode"),
                             ("RESTOCK_STAFF_PASSCODE", "staff_passcode")):
        if os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]
    wa_env = {
        "provider": os.environ.get("RESTOCK_WHATSAPP_PROVIDER", ""),
        "callmebot_phone": os.environ.get("RESTOCK_CALLMEBOT_PHONE", ""),
        "callmebot_apikey": os.environ.get("RESTOCK_CALLMEBOT_APIKEY", ""),
        "twilio_sid": os.environ.get("RESTOCK_TWILIO_SID", ""),
        "twilio_token": os.environ.get("RESTOCK_TWILIO_TOKEN", ""),
        "twilio_from": os.environ.get("RESTOCK_TWILIO_FROM", ""),
        "twilio_to": os.environ.get("RESTOCK_TWILIO_TO", ""),
    }
    if any(wa_env.values()):
        cfg["whatsapp"] = {k: v for k, v in wa_env.items() if v}

    # config.json (present locally) takes precedence over env + defaults.
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        for k, v in data.items():
            if k in ("whatsapp", "channels") or v not in (None, ""):
                cfg[k] = v

    if isinstance(cfg["recipients"], str):
        cfg["recipients"] = [r.strip() for r in cfg["recipients"].split(",") if r.strip()]
    if isinstance(cfg.get("channels"), str):
        cfg["channels"] = [c.strip() for c in cfg["channels"].split(",") if c.strip()]
    return cfg


def build_digest():
    """Return a structured summary of what needs attention right now."""
    items = store.list_items()
    buckets = {"low": [], "overdue": [], "due": [], "soon": []}
    for it in items:
        if it["status"] in buckets:
            buckets[it["status"]].append(it)
    suggestions = [it for it in items if it["suggestion"]]
    needs_attention = any(buckets.values()) or bool(suggestions)
    return {"buckets": buckets, "suggestions": suggestions,
            "needs_attention": needs_attention, "total": len(items)}


def _fmt_line(it):
    who = f"[{it['owner']}]"
    when = ("OVERDUE" if it["days_until"] < 0
            else "due today" if it["days_until"] == 0
            else f"in {it['days_until']} day(s)")
    qty = f" ({it['quantity']} {it['unit']})".rstrip() if it["quantity"] else ""
    return f"  • {it['name']}{qty} {who} — {when}"


def render_text(digest):
    lines = ["Weekly Supply Restock — status\n"]
    labels = [("low", "🔴 Running LOW (flagged off-schedule)"),
              ("overdue", "🟠 Overdue"),
              ("due", "🟡 Due today"),
              ("soon", "🔵 Coming up soon")]
    for key, label in labels:
        rows = digest["buckets"][key]
        if rows:
            lines.append(label)
            lines.extend(_fmt_line(it) for it in rows)
            lines.append("")
    if digest["suggestions"]:
        lines.append("💡 Schedule suggestions (need your approval):")
        for it in digest["suggestions"]:
            s = it["suggestion"]
            lines.append(f"  • {it['name']}: every {s['from_cadence']} → "
                         f"{s['to_cadence']} days. {s['reason']}")
        lines.append("")
    if not digest["needs_attention"]:
        lines.append("All good — nothing needs restocking right now. ✅")
    return "\n".join(lines).rstrip() + "\n"


def render_html(digest):
    def block(label, color, rows):
        if not rows:
            return ""
        lis = "".join(
            f"<li><b>{it['name']}</b>"
            + (f" <span style='color:#666'>({it['quantity']} {it['unit']})</span>"
               if it['quantity'] else "")
            + f" <span style='color:#888'>[{it['owner']}]</span> — "
            + ("<b style='color:#c0392b'>OVERDUE</b>" if it['days_until'] < 0
               else "due today" if it['days_until'] == 0
               else f"in {it['days_until']} day(s)") + "</li>"
            for it in rows)
        return (f"<h3 style='margin:16px 0 4px;color:{color}'>{label}</h3>"
                f"<ul style='margin:0 0 8px;padding-left:20px'>{lis}</ul>")

    parts = ["<div style='font-family:-apple-system,Segoe UI,Arial,sans-serif;"
             "max-width:560px;color:#222'>",
             "<h2>Weekly Supply Restock</h2>"]
    parts.append(block("🔴 Running low (flagged off-schedule)", "#c0392b",
                       digest["buckets"]["low"]))
    parts.append(block("🟠 Overdue", "#e67e22", digest["buckets"]["overdue"]))
    parts.append(block("🟡 Due today", "#b7950b", digest["buckets"]["due"]))
    parts.append(block("🔵 Coming up soon", "#2471a3", digest["buckets"]["soon"]))
    if digest["suggestions"]:
        rows = "".join(
            f"<li><b>{it['name']}</b>: every {it['suggestion']['from_cadence']} → "
            f"{it['suggestion']['to_cadence']} days. "
            f"<span style='color:#666'>{it['suggestion']['reason']}</span></li>"
            for it in digest["suggestions"])
        parts.append("<h3 style='margin:16px 0 4px;color:#6c3483'>💡 Schedule "
                     "suggestions (need approval)</h3>"
                     f"<ul style='padding-left:20px'>{rows}</ul>")
    if not digest["needs_attention"]:
        parts.append("<p>All good — nothing needs restocking right now. ✅</p>")
    parts.append("</div>")
    return "".join(parts)


def email_ready(cfg):
    return (all(cfg.get(k) for k in
                ("smtp_host", "smtp_user", "smtp_password", "from_addr"))
            and bool(cfg.get("recipients")))


def whatsapp_ready(cfg):
    wa = cfg.get("whatsapp") or {}
    provider = wa.get("provider")
    if provider == "callmebot":
        return bool(wa.get("callmebot_phone") and wa.get("callmebot_apikey"))
    if provider == "twilio":
        return bool(wa.get("twilio_sid") and wa.get("twilio_token")
                    and wa.get("twilio_from") and wa.get("twilio_to"))
    return False


def _send_email(cfg, digest):
    msg = EmailMessage()
    n = sum(len(v) for v in digest["buckets"].values())
    msg["Subject"] = (f"Restock: {n} item(s) need attention"
                      if n else "Restock: schedule suggestions")
    msg["From"] = cfg["from_addr"]
    msg["To"] = ", ".join(cfg["recipients"])
    msg.set_content(render_text(digest))
    msg.add_alternative(render_html(digest), subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as s:
        s.starttls(context=context)
        s.login(cfg["smtp_user"], cfg["smtp_password"])
        s.send_message(msg)
    return f"emailed to {', '.join(cfg['recipients'])}"


def _send_whatsapp(cfg, digest):
    wa = cfg["whatsapp"]
    text = render_text(digest)
    if wa["provider"] == "callmebot":
        # CallMeBot: simplest way to send WhatsApp to *your own* number.
        phone = wa["callmebot_phone"].lstrip("+")
        params = urllib.parse.urlencode({
            "phone": phone, "text": text, "apikey": wa["callmebot_apikey"]})
        url = "https://api.callmebot.com/whatsapp.php?" + params
        with urllib.request.urlopen(url, timeout=20) as r:
            r.read()
        return f"WhatsApp sent to +{phone}"
    if wa["provider"] == "twilio":
        sid, token = wa["twilio_sid"], wa["twilio_token"]
        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        data = urllib.parse.urlencode({
            "From": wa["twilio_from"], "To": wa["twilio_to"], "Body": text}).encode()
        req = urllib.request.Request(endpoint, data=data)
        creds = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req.add_header("Authorization", "Basic " + creds)
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        return f"WhatsApp sent to {wa['twilio_to']}"
    raise ValueError("Unknown WhatsApp provider")


def send_digest(cfg=None, force=False):
    """Send the digest on every configured channel. Returns (sent, message)."""
    cfg = cfg or load_config()
    digest = build_digest()

    if not force and not digest["needs_attention"]:
        return False, "Nothing needs attention — nothing sent."

    channels = cfg.get("channels") or ["email"]
    results, errors = [], []

    if "email" in channels:
        if email_ready(cfg):
            try:
                results.append(_send_email(cfg, digest))
            except Exception as e:
                errors.append(f"email failed: {e}")
        else:
            errors.append("email not configured")

    if "whatsapp" in channels:
        if whatsapp_ready(cfg):
            try:
                results.append(_send_whatsapp(cfg, digest))
            except Exception as e:
                errors.append(f"WhatsApp failed: {e}")
        else:
            errors.append("WhatsApp not configured")

    if results:
        msg = "Digest " + "; ".join(results) + "."
        if errors:
            msg += " (Also: " + "; ".join(errors) + ".)"
        return True, msg
    return False, "Not sent — " + "; ".join(errors or ["no channels enabled"]) + "."


if __name__ == "__main__":
    # Run directly (e.g. from a scheduled job) to send today's digest.
    store.init_db()
    sent, message = send_digest()
    print(message)
