"""Optional local->GitHub data sync.

When the local website is used to add/edit items, this pushes the updated
restock.db up to the GitHub repo so the daily cloud digest (GitHub Actions)
always reads the latest schedule.

Enabled only when RESTOCK_GIT_SYNC=1 and the folder has a git remote. It is a
best-effort background task: if you're offline or a push fails, the site keeps
working locally and the next change re-attempts the push.
"""

import os
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "restock.db")
CHECK_EVERY = 120  # seconds


def _git(*args):
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)


def _has_remote():
    return _git("remote").stdout.strip() != ""


def _push_if_changed(last_mtime):
    try:
        mtime = os.path.getmtime(DB_PATH)
    except OSError:
        return last_mtime
    if mtime == last_mtime:
        return last_mtime

    # Stage and commit only the data file; skip if nothing actually changed.
    _git("add", "restock.db")
    status = _git("status", "--porcelain", "restock.db").stdout.strip()
    if status:
        _git("commit", "-m", "Sync restock data")
        push = _git("push", "origin", "HEAD")
        if push.returncode != 0:
            # Leave last_mtime unchanged so we retry next cycle.
            print("[sync] push failed:", push.stderr.strip()[:200])
            return last_mtime
        print("[sync] data pushed to GitHub")
    return mtime


def _loop():
    if not _has_remote():
        print("[sync] no git remote configured — data sync disabled")
        return
    print("[sync] watching restock.db; will push changes to GitHub")
    last = 0.0
    while True:
        last = _push_if_changed(last)
        time.sleep(CHECK_EVERY)


def start_if_enabled():
    if os.environ.get("RESTOCK_GIT_SYNC") == "1":
        threading.Thread(target=_loop, daemon=True).start()
