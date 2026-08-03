"""In-process daily scheduler for the always-on (hosted) deployment.

When RESTOCK_DAILY_TIME is set (e.g. "08:00"), a background thread sends the
digest once per day at that time — using the server's local clock. On a cloud
host, set TZ (e.g. TZ=Asia/Dubai) so "08:00" means 8am in your timezone.

A small state file records the last date sent, so a restart won't double-send.
"""

import os
import threading
import time
from datetime import datetime

import notify

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("RESTOCK_DATA_DIR") or HERE
STATE_PATH = os.path.join(DATA_DIR, ".last_digest")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _already_sent_today():
    try:
        with open(STATE_PATH) as f:
            return f.read().strip() == _today()
    except OSError:
        return False


def _mark_sent_today():
    try:
        with open(STATE_PATH, "w") as f:
            f.write(_today())
    except OSError as e:
        print("[scheduler] could not write state:", e)


def _loop(hour, minute):
    print(f"[scheduler] daily digest scheduled for {hour:02d}:{minute:02d} "
          f"(server local time)")
    while True:
        now = datetime.now()
        if (now.hour, now.minute) >= (hour, minute) and not _already_sent_today():
            try:
                _, message = notify.send_digest()
                print("[scheduler]", message)
            except Exception as e:  # never let the thread die
                print("[scheduler] send error:", e)
            _mark_sent_today()
        time.sleep(30)


def start_if_enabled():
    value = os.environ.get("RESTOCK_DAILY_TIME")
    if not value:
        return
    try:
        hour, minute = (int(x) for x in value.split(":"))
    except (ValueError, TypeError):
        print(f"[scheduler] invalid RESTOCK_DAILY_TIME '{value}' (want HH:MM)")
        return
    threading.Thread(target=_loop, args=(hour, minute), daemon=True).start()
