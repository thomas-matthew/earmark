"""The local record of every saved item Earmark has seen (T1). Items are never deleted from it."""
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

# Item lifecycle:
#   baseline  seen on the first run but older than the look-back window; never processed
#   new       waiting for the relevance check (Reddit and X) or for processing
#   skipped   the relevance check decided it is not worth an episode
#   done      episode published
#   expired   episode audio deleted after the retention period
#   failed    gave up after repeated errors; an "unreadable" episode was published instead
STATUSES = ("baseline", "new", "skipped", "done", "expired", "failed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    link TEXT,
    item_date REAL NOT NULL,
    discovered_at REAL NOT NULL,
    sort_at REAL NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    decision TEXT,
    decision_reason TEXT,
    decision_confidence TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    episode_title TEXT,
    description TEXT,
    mp3 TEXT,
    bytes INTEGER,
    seconds REAL,
    published_at REAL
);
CREATE INDEX IF NOT EXISTS items_status ON items (status);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class Item:
    """One saved item as a source reports it."""
    id: str
    source: str
    kind: str
    title: str
    url: str
    item_date: float
    link: str | None = None
    payload: dict = field(default_factory=dict)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def known_ids(db: sqlite3.Connection, source: str) -> set[str]:
    return {row[0] for row in db.execute("SELECT id FROM items WHERE source=?", (source,))}


def insert(db: sqlite3.Connection, item: Item, status: str, sort_at: float | None = None) -> bool:
    """Record an item once. Returns False if it was already known."""
    now = time.time()
    cur = db.execute(
        "INSERT OR IGNORE INTO items (id, source, kind, title, url, link, item_date, discovered_at, sort_at, payload, status)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (item.id, item.source, item.kind, item.title, item.url, item.link, item.item_date, now,
         sort_at if sort_at is not None else now, json.dumps(item.payload, ensure_ascii=False), status),
    )
    db.commit()
    return cur.rowcount == 1


def update(db: sqlite3.Connection, item_id: str, **fields) -> None:
    columns = ", ".join(f"{name}=?" for name in fields)
    db.execute(f"UPDATE items SET {columns} WHERE id=?", (*fields.values(), item_id))
    db.commit()


def get(db: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()


def pending(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Items still to process, newest first (A5), so the first episodes arrive early."""
    return db.execute("SELECT * FROM items WHERE status='new' ORDER BY sort_at DESC").fetchall()


def meta_get(db: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    db.commit()
