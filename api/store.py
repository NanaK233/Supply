"""Data layer for the restock site — PostgreSQL (psycopg2).

Uses the POSTGRES_URL (or DATABASE_URL) environment variable. A tiny connection
adapter mimics the sqlite3 API (execute/executescript/commit/close and ?-style
placeholders) so the rest of the module reads the same as the original SQLite
version — only the plumbing changed.
"""

import os
import re
from datetime import date, datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor

OWNERS = ["Eddie", "Danilo", "Shared"]

# How many days before the due date an item is considered "coming up soon".
DEFAULT_LEAD_DAYS = 2

# Adaptive cadence: how many early low-flags (since the last cadence change)
# before we suggest tightening the schedule.
SUGGEST_AFTER_EARLY_FLAGS = 2


def _dsn():
    dsn = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("POSTGRES_URL (or DATABASE_URL) environment variable is required")
    return dsn


class _Conn:
    """sqlite3-style wrapper around a psycopg2 connection so the rest of the
    module can keep using conn.execute('... ?', params).fetchone()."""

    def __init__(self):
        self._c = psycopg2.connect(_dsn())

    def execute(self, sql, params=()):
        cur = self._c.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params or None)
        return cur

    def executescript(self, script):
        cur = self._c.cursor()
        cur.execute(script)
        cur.close()

    def commit(self):
        self._c.commit()

    def close(self):
        self._c.close()


def _connect():
    return _Conn()


def init_db():
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS items (
            id              SERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            owner           TEXT NOT NULL DEFAULT 'Shared',
            category        TEXT DEFAULT '',
            quantity        TEXT DEFAULT '',
            unit            TEXT DEFAULT '',
            cadence_days    INTEGER NOT NULL DEFAULT 7,
            last_restocked  TEXT NOT NULL,
            notes           TEXT DEFAULT '',
            archived        INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            restock_state   TEXT NOT NULL DEFAULT '',
            quantity_needed TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS events (
            id         SERIAL PRIMARY KEY,
            item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            type       TEXT NOT NULL,
            days_early INTEGER,
            detail     TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suggestion_dismissals (
            item_id      INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
            dismissed_at TEXT NOT NULL
        );
        """
    )
    # Legacy rename (harmless on a fresh database).
    conn.execute("UPDATE items SET restock_state='ordered' WHERE restock_state='restocking'")
    conn.commit()
    conn.close()


def _today():
    return date.today()


def _parse(d):
    return datetime.strptime(d, "%Y-%m-%d").date()


def _parse_qty(q):
    """Pull the leading number out of a free-text quantity like '0', '0 boxes',
    '6 Bottles'. Returns a float, or None when no number is present (i.e. the
    stock level simply hasn't been recorded — which is NOT the same as empty)."""
    if q is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(q))
    return float(m.group()) if m else None


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def _last_restock_change_date(conn, item):
    """The reference date for adaptive logic: the later of last_restocked
    and the most recent cadence change."""
    row = conn.execute(
        "SELECT created_at FROM events WHERE item_id=? AND type='cadence_changed' "
        "ORDER BY created_at DESC LIMIT 1",
        (item["id"],),
    ).fetchone()
    dates = [_parse(item["last_restocked"])]
    if row:
        dates.append(_parse(row["created_at"][:10]))
    return max(dates)


def _open_low_flag(conn, item):
    """A low flag counts as 'still low' only if raised after the most recent
    restock. Using the restock event's full timestamp (not just the date) means
    marking an item restocked clears a low flag raised earlier the same day."""
    restocked = conn.execute(
        "SELECT created_at FROM events WHERE item_id=? AND type='restocked' "
        "ORDER BY created_at DESC LIMIT 1",
        (item["id"],),
    ).fetchone()
    ref = restocked["created_at"] if restocked else item["last_restocked"]
    row = conn.execute(
        "SELECT created_at FROM events WHERE item_id=? AND type='flagged_low' "
        "AND created_at > ? ORDER BY created_at DESC LIMIT 1",
        (item["id"], ref),
    ).fetchone()
    return row is not None


def _suggestion_for(conn, item):
    """Suggest a tighter cadence when an item keeps getting flagged low
    *before* its due date. Returns a dict or None."""
    ref = _last_restock_change_date(conn, item)
    flags = conn.execute(
        "SELECT days_early FROM events WHERE item_id=? AND type='flagged_low' "
        "AND created_at >= ? AND days_early IS NOT NULL",
        (item["id"], ref.isoformat()),
    ).fetchall()
    early = [f["days_early"] for f in flags if f["days_early"] is not None and f["days_early"] > 0]
    if len(early) < SUGGEST_AFTER_EARLY_FLAGS:
        return None

    # Suggested cadence = current cadence minus the typical shortfall.
    avg_early = sum(early) / len(early)
    suggested = max(1, round(item["cadence_days"] - avg_early))
    if suggested >= item["cadence_days"]:
        return None

    # Respect a dismissal unless there's a flag newer than the dismissal.
    dis = conn.execute(
        "SELECT dismissed_at FROM suggestion_dismissals WHERE item_id=?",
        (item["id"],),
    ).fetchone()
    if dis:
        newer = conn.execute(
            "SELECT 1 FROM events WHERE item_id=? AND type='flagged_low' "
            "AND created_at > ? LIMIT 1",
            (item["id"], dis["dismissed_at"]),
        ).fetchone()
        if not newer:
            return None

    return {
        "from_cadence": item["cadence_days"],
        "to_cadence": suggested,
        "reason": f"Flagged low early {len(early)}× — running out about "
                  f"{round(avg_early)} day(s) before schedule.",
    }


def _decorate(conn, row, lead_days=DEFAULT_LEAD_DAYS):
    item = dict(row)
    last = _parse(item["last_restocked"])
    due = last + timedelta(days=item["cadence_days"])
    days_until = (due - _today()).days
    is_low = _open_low_flag(conn, item)

    # Empty = an explicitly recorded on-hand count of zero (or less).
    qty_num = _parse_qty(item.get("quantity"))
    is_empty = qty_num is not None and qty_num <= 0

    # An item always shows its real stock status: empty → Out of stock, flagged →
    # Running low, else date-based. 'ordered' is an INDEPENDENT flag — an ordered
    # item ALSO counts under "Coming up" on the dashboard (it appears in both its
    # own bucket and Coming up), surfaced via item['ordered'] + the 🛒 badge.
    manual = item.get("restock_state") or ""
    is_ordered = manual == "ordered"
    if is_empty or manual == "out_of_stock":
        status = "out"
    elif is_low:
        status = "low"
    elif days_until < 0:
        status = "overdue"
    elif days_until == 0:
        status = "due"
    elif days_until <= lead_days:
        status = "soon"
    else:
        status = "ok"

    item["next_due"] = due.isoformat()
    item["days_until"] = days_until
    item["status"] = status
    item["is_low"] = is_low
    item["is_empty"] = is_empty
    item["ordered"] = is_ordered
    item["restock_state"] = manual
    item["suggestion"] = _suggestion_for(conn, item)
    return item


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_items(include_archived=False, owners=None):
    conn = _connect()
    q = "SELECT * FROM items"
    conds, params = [], []
    if not include_archived:
        conds.append("archived=0")
    if owners is not None:  # restrict to these owners (e.g. staff: [name, 'Shared'])
        conds.append("owner IN (%s)" % ",".join("?" * len(owners)))
        params.extend(owners)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    rows = conn.execute(q, params).fetchall()
    items = [_decorate(conn, r) for r in rows]
    conn.close()

    order = {"out": 0, "low": 1, "overdue": 2, "due": 3, "soon": 4, "ok": 5}
    items.sort(key=lambda i: (order.get(i["status"], 9), i["days_until"]))
    return items


def get_item(item_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    item = _decorate(conn, row) if row else None
    conn.close()
    return item


def create_item(data):
    conn = _connect()
    now = datetime.now().isoformat(timespec="seconds")
    last = data.get("last_restocked") or _today().isoformat()
    cur = conn.execute(
        "INSERT INTO items (name, owner, category, quantity, unit, cadence_days, "
        "last_restocked, notes, quantity_needed, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (
            data["name"].strip(),
            data.get("owner", "Shared"),
            data.get("category", "").strip(),
            str(data.get("quantity", "")).strip(),
            data.get("unit", "").strip(),
            int(data.get("cadence_days", 7)),
            last,
            data.get("notes", "").strip(),
            str(data.get("quantity_needed", "")).strip(),
            now,
        ),
    )
    item_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return get_item(item_id)


def update_item(item_id, data):
    conn = _connect()
    existing = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not existing:
        conn.close()
        return None

    old_cadence = existing["cadence_days"]
    fields = ["name", "owner", "category", "quantity", "unit", "cadence_days",
              "last_restocked", "notes", "quantity_needed"]
    updates = {f: data[f] for f in fields if f in data}
    if "cadence_days" in updates:
        updates["cadence_days"] = int(updates["cadence_days"])

    if updates:
        cols = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE items SET {cols} WHERE id=?",
                     (*updates.values(), item_id))
        if "cadence_days" in updates and updates["cadence_days"] != old_cadence:
            _log_event(conn, item_id, "cadence_changed",
                       detail=f"{old_cadence} -> {updates['cadence_days']} days")
        conn.commit()
    conn.close()
    return get_item(item_id)


def update_quantity(item_id, quantity, unit=None, needed=None):
    """Update the on-hand stock level (and optionally the unit / quantity needed).

    Refreshing stock to a positive amount means the order arrived: this clears any
    'ordered'/'out of stock' state and the running-low flag, so the item stops
    showing as urgent. Setting it to 0 (or leaving it empty) does not clear those.
    """
    conn = _connect()
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return None
    quantity = str(quantity).strip()
    sets, params = ["quantity=?"], [quantity]
    if unit is not None:
        sets.append("unit=?"); params.append(unit.strip())
    if needed is not None:
        sets.append("quantity_needed=?"); params.append(str(needed).strip())
    params.append(item_id)
    conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", params)

    qty_num = _parse_qty(quantity)
    if qty_num is not None and qty_num > 0:
        if (row["restock_state"] or "") in ("ordered", "out_of_stock"):
            conn.execute("UPDATE items SET restock_state='' WHERE id=?", (item_id,))
        # A live low flag is cleared by recording a stock refresh (schedule stays).
        if _open_low_flag(conn, row):
            _log_event(conn, item_id, "restocked", detail="stock refreshed")
    conn.commit()
    conn.close()
    return get_item(item_id)


def delete_item(item_id):
    conn = _connect()
    conn.execute("UPDATE items SET archived=1 WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return True


def _log_event(conn, item_id, etype, days_early=None, detail=""):
    # microsecond precision so two events in the same second still order correctly
    # (e.g. a stock refresh vs. a low flag), which the low-flag check depends on.
    conn.execute(
        "INSERT INTO events (item_id, type, days_early, detail, created_at) "
        "VALUES (?,?,?,?,?)",
        (item_id, etype, days_early, detail,
         datetime.now().isoformat(timespec="microseconds")),
    )


def mark_restocked(item_id):
    """Reset the clock: next due = today + cadence, and clear any manual state."""
    conn = _connect()
    today = _today().isoformat()
    conn.execute("UPDATE items SET last_restocked=?, restock_state='' WHERE id=?",
                 (today, item_id))
    _log_event(conn, item_id, "restocked")
    conn.commit()
    conn.close()
    return get_item(item_id)


# Values accepted by set_restock_state, mapped to the DB column value.
RESTOCK_STATES = {"out_of_stock", "ordered", "restocked"}


def set_restock_state(item_id, state):
    """Apply a workflow state from the status menu.

    'restocked'   -> reset the clock (delegates to mark_restocked)
    'out_of_stock'/'ordered' -> set the manual state, keep the schedule.
    """
    if state == "restocked":
        return mark_restocked(item_id)
    if state not in ("out_of_stock", "ordered"):
        return None
    conn = _connect()
    row = conn.execute("SELECT id FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("UPDATE items SET restock_state=? WHERE id=?", (state, item_id))
    _log_event(conn, item_id, state)
    conn.commit()
    conn.close()
    return get_item(item_id)


def flag_low(item_id):
    """Someone reports the item is running low off-schedule. Record how many
    days early that is, which feeds the adaptive-cadence suggestion."""
    conn = _connect()
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return None
    last = _parse(row["last_restocked"])
    due = last + timedelta(days=row["cadence_days"])
    days_early = (due - _today()).days  # positive => flagged before due date
    _log_event(conn, item_id, "flagged_low", days_early=days_early)
    conn.commit()
    conn.close()
    return get_item(item_id)


def apply_suggestion(item_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    item = _decorate(conn, row) if row else None
    if not item or not item["suggestion"]:
        conn.close()
        return None
    new_cadence = item["suggestion"]["to_cadence"]
    old_cadence = item["cadence_days"]
    conn.execute("UPDATE items SET cadence_days=? WHERE id=?", (new_cadence, item_id))
    _log_event(conn, item_id, "cadence_changed",
               detail=f"{old_cadence} -> {new_cadence} days (approved suggestion)")
    conn.execute("DELETE FROM suggestion_dismissals WHERE item_id=?", (item_id,))
    conn.commit()
    conn.close()
    return get_item(item_id)


def dismiss_suggestion(item_id):
    conn = _connect()
    conn.execute(
        "INSERT INTO suggestion_dismissals (item_id, dismissed_at) VALUES (?,?) "
        "ON CONFLICT (item_id) DO UPDATE SET dismissed_at=excluded.dismissed_at",
        (item_id, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return get_item(item_id)


def history(item_id, limit=20):
    conn = _connect()
    rows = conn.execute(
        "SELECT type, days_early, detail, created_at FROM events "
        "WHERE item_id=? ORDER BY created_at DESC LIMIT ?",
        (item_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
