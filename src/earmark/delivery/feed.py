"""The podcast feed (A3, A5): one RSS entry per published episode, newest saved first."""
import sqlite3
from email.utils import formatdate
from pathlib import Path
from xml.sax.saxutils import escape

FEED_NAME = "feed.xml"


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def write_feed(db: sqlite3.Connection, feed_dir: Path, base_url: str) -> Path:
    """Rewrite the feed from the database. Listening progress is left to AntennaPod (T2)."""
    entries = []
    for row in db.execute("SELECT * FROM items WHERE status IN ('done', 'failed') AND mp3 IS NOT NULL ORDER BY sort_at DESC"):
        entries.append(f"""  <item>
    <title>{escape(row['episode_title'] or row['title'])}</title>
    <guid isPermaLink="false">{escape(row['id'])}</guid>
    <link>{escape(row['url'])}</link>
    <description>{escape(row['description'] or row['url'])}</description>
    <pubDate>{formatdate(row['sort_at'])}</pubDate>
    <enclosure url="{_attr(f"{base_url}/{row['mp3']}")}" length="{row['bytes']}" type="audio/mpeg"/>
    <itunes:duration>{round(row['seconds'] or 0)}</itunes:duration>
  </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>Earmark</title>
  <link>{escape(base_url)}/{FEED_NAME}</link>
  <description>Things I saved, retold for listening.</description>
  <language>en</language>
  <itunes:block>Yes</itunes:block>
{chr(10).join(entries)}
</channel>
</rss>
"""
    feed_dir.mkdir(parents=True, exist_ok=True)
    path = feed_dir / FEED_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(feed, encoding="utf-8")
    tmp.replace(path)  # atomic, so the server never serves half a feed
    return path
