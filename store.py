"""SQLite-backed store for demo bookings and orders.

Bookings and orders persist in bookings.db next to this file, so a
server restart keeps the demo state (the previous version kept
everything in memory and lost it on restart). The DB file is
gitignored — see .gitignore — and is created automatically on first
import. Same function API as the previous in-memory version, so
app.py only needed two small adjustments: deposit order ids are now
persisted through set_deposit_order_id(), and the chat cancel branch
re-fetches the booking so the reply carries the fresh status.
"""

import json
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    service TEXT NOT NULL,
    date_time TEXT NOT NULL,
    deposit_order_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init():
    with _conn() as conn:
        conn.executescript(_SCHEMA)


_init()


def _booking_from_row(row):
    return dict(row) if row is not None else None


def _next_booking_id(conn):
    row = conn.execute(
        "SELECT MAX(CAST(substr(id, 5) AS INTEGER)) AS m FROM bookings"
    ).fetchone()
    return f"BKG-{(row['m'] or 0) + 1:04d}"


def create_booking(customer_name, service, date_time, deposit_order_id=None):
    with _conn() as conn:
        booking_id = _next_booking_id(conn)
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO bookings (id, customer_name, service, date_time,"
            " deposit_order_id, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'pending_deposit', ?)",
            (booking_id, customer_name, service, date_time,
             deposit_order_id, created_at),
        )
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        return _booking_from_row(row)


def get_booking(booking_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        return _booking_from_row(row)


def confirm_booking(booking_id):
    with _conn() as conn:
        conn.execute(
            "UPDATE bookings SET status = 'confirmed' WHERE id = ?",
            (booking_id,),
        )
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        return _booking_from_row(row)


def cancel_booking(booking_id):
    with _conn() as conn:
        conn.execute(
            "UPDATE bookings SET status = 'cancelled'"
            " WHERE id = ? AND status != 'confirmed'",
            (booking_id,),
        )
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        return _booking_from_row(row)


def set_deposit_order_id(booking_id, order_id):
    """Persist the deposit order link (replaces in-memory dict mutation)."""
    with _conn() as conn:
        conn.execute(
            "UPDATE bookings SET deposit_order_id = ? WHERE id = ?",
            (order_id, booking_id),
        )


def record_order(order):
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO orders (id, payload) VALUES (?, ?)",
            (order["id"], json.dumps(order)),
        )
    return order


def get_order(order_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT payload FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row is not None else None


def list_bookings():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings ORDER BY created_at, id"
        ).fetchall()
        return [_booking_from_row(r) for r in rows]
