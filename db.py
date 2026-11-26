# db.py - the database code (bookings)
#
# Step 4: create the bookings table, free_slots() and book()
#
import datetime
import sqlite3

DB_FILE = "bookings.db"
SLOTS = ["10:00", "11:30", "14:00", "15:30", "17:00"]  # clinic opening times


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            date       TEXT NOT NULL,
            time       TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, time)
        )
    """)
    return conn


def free_slots(date: str) -> list[str]:
    day = datetime.date.fromisoformat(date)
    now = datetime.datetime.now()
    if day < now.date() or day.weekday() == 6:  # a past day, or Sunday (closed)
        return []
    with _connect() as conn:
        rows = conn.execute("SELECT time FROM bookings WHERE date = ?", (date,))
        taken = {row[0] for row in rows}
    free = [s for s in SLOTS if s not in taken]
    if day == now.date():  # today: hide times that already passed
        free = [s for s in free if s > now.strftime("%H:%M")]
    return free


def book(name: str, date: str, time: str) -> int | None:
    if time not in free_slots(date):
        return None  # not a clinic time, taken, already passed, or Sunday
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO bookings (name, date, time) VALUES (?, ?, ?)",
                (name, date, time),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # slot already taken
