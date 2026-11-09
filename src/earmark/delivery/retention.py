"""Delete episode audio after the retention period (T3). The item record stays, so it is never redone."""
import sqlite3
import time
from pathlib import Path

from ..storage import db as store


def expire(db: sqlite3.Connection, feed_dir: Path, days: int, now: float | None = None) -> int:
    cutoff = (now or time.time()) - days * 86400
    rows = db.execute("SELECT id, mp3 FROM items WHERE status IN ('done', 'failed') AND mp3 IS NOT NULL "
                      "AND published_at < ?", (cutoff,)).fetchall()
    for row in rows:
        (feed_dir / row["mp3"]).unlink(missing_ok=True)
        store.update(db, row["id"], status="expired", mp3=None)
    return len(rows)
