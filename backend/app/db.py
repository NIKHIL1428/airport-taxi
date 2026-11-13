"""SQLite storage for everything the app creates. Survives restarts (M5, state rule)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS ride_requests (
    request_id     TEXT PRIMARY KEY,
    traveler_name  TEXT NOT NULL,
    flight_id      TEXT NOT NULL,
    hotel_id       TEXT NOT NULL,
    adults         INTEGER NOT NULL,
    child_ages     TEXT NOT NULL,              -- JSON list of ints
    large_bags     INTEGER NOT NULL,
    small_bags     INTEGER NOT NULL,
    pickup         TEXT NOT NULL,              -- local time of arrival airport, YYYY-MM-DDTHH:MM
    car_type       TEXT,                       -- NULL = any type (G2)
    price_inr      INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | BOOKED | CANCELLED
    source         TEXT NOT NULL DEFAULT 'APP',    -- APP | SEED (open_requests.json)
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (               -- an "assigned taxi"
    offer_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT NOT NULL REFERENCES ride_requests(request_id),
    company_id  TEXT NOT NULL,
    vehicle_id  TEXT NOT NULL,
    price_inr   INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN | BOOKED | REJECTED | NOT_CHOSEN | CAR_TAKEN | CANCELLED
    hold_until  TEXT,                          -- guaranteed window: the car is held for this traveler until then
    share_group TEXT,                          -- S1 shared ride: both families' offers have the same group
    shared_pickup TEXT,                        -- S1: pickup of the shared car (the later of the two pickups)
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_no  TEXT PRIMARY KEY,              -- unique 10-digit number
    request_id  TEXT NOT NULL REFERENCES ride_requests(request_id),
    offer_id    INTEGER NOT NULL REFERENCES offers(offer_id),
    company_id  TEXT NOT NULL,
    vehicle_id  TEXT NOT NULL,
    flight_id   TEXT NOT NULL,
    pickup      TEXT NOT NULL,
    busy_start  TEXT NOT NULL,                 -- R6 busy time of the car
    busy_end    TEXT NOT NULL,
    price_inr   INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'CONFIRMED',  -- CONFIRMED | CANCELLED
    share_group TEXT,                          -- S1: set while the car is shared with another family
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_requests (
    change_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_no     TEXT NOT NULL REFERENCES bookings(booking_no),
    new_flight_id  TEXT,                         -- NULL = same flight
    new_pickup     TEXT,                         -- NULL = earliest pickup of the (new) flight
    old_flight_id  TEXT,                         -- the booking before the change (for the history)
    old_pickup     TEXT,
    status         TEXT NOT NULL DEFAULT 'WAITING',  -- WAITING | ACCEPTED | REJECTED
    reason         TEXT,
    created_at     TEXT NOT NULL,
    decided_at     TEXT
);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path=None) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may open the connection (in get_db) on one worker thread
    # and run the endpoint on another. That is safe here because every HTTP request gets its
    # own connection, which is never shared. timeout: wait up to 10 s if another request is writing.
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """FastAPI dependency: one connection per HTTP request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Older databases had offers.expires_at and an EXPIRED status: move them to the guarantee model.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    for column in ("hold_until", "share_group", "shared_pickup"):
        if column not in columns:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {column} TEXT")
    if "share_group" not in {row[1] for row in conn.execute("PRAGMA table_info(bookings)")}:
        conn.execute("ALTER TABLE bookings ADD COLUMN share_group TEXT")
    conn.execute("UPDATE offers SET status = 'OPEN' WHERE status = 'EXPIRED'")
    change_columns = {row[1] for row in conn.execute("PRAGMA table_info(change_requests)")}
    for column in ("old_flight_id", "old_pickup"):
        if column not in change_columns:
            conn.execute(f"ALTER TABLE change_requests ADD COLUMN {column} TEXT")
    conn.commit()


def seed_open_requests(conn: sqlite3.Connection, open_requests: list[dict]) -> int:
    """Load open_requests.json once. INSERT OR IGNORE keeps it safe across restarts."""
    added = 0
    for r in open_requests:
        cur = conn.execute(
            """INSERT OR IGNORE INTO ride_requests
               (request_id, traveler_name, flight_id, hotel_id, adults, child_ages,
                large_bags, small_bags, pickup, car_type, price_inr, status, source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'OPEN', 'SEED', ?)""",
            (
                r["request_id"], r.get("traveler_name") or "Traveler", r["flight_id"], r["hotel_id"],
                r["adults"], json.dumps(r.get("child_ages") or []), r["large_bags"], r["small_bags"],
                r["pickup"][:16], r.get("car_type"), r["price_inr"], now_iso(),
            ),
        )
        added += cur.rowcount
    conn.commit()
    return added
