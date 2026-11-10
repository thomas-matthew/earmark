import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer

import pytest

from earmark import config
from earmark.delivery import retention
from earmark.delivery.feed import write_feed
from earmark.delivery.server import make_handler, parse_range
from earmark.storage import db as store
from earmark.storage.db import Item


def test_env_file_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nREDDIT_SESSION="abc=def"\nNTFY_TOPIC=earmark-xyz\nEARMARK_PORT=9000\n')
    settings = config.load(env)
    assert settings.secret("REDDIT_SESSION") == "abc=def"
    assert settings.ntfy_topic == "earmark-xyz"
    assert settings.port == 9000


def test_items_are_recorded_once_and_pending_is_newest_first(ctx):
    assert store.insert(ctx.db, Item("hn:1", "hn", "story", "Old", "u1", 100.0), "new", sort_at=100.0)
    assert store.insert(ctx.db, Item("hn:2", "hn", "story", "New", "u2", 200.0), "new", sort_at=200.0)
    assert not store.insert(ctx.db, Item("hn:1", "hn", "story", "Again", "u1", 100.0), "new")
    assert [r["id"] for r in store.pending(ctx.db)] == ["hn:2", "hn:1"]
    assert store.known_ids(ctx.db, "hn") == {"hn:1", "hn:2"}


def _publish(ctx, item_id, sort_at, published_at, title="A & B <test>"):
    store.insert(ctx.db, Item(item_id, "hn", "story", title, f"https://example.com/{item_id}", sort_at), "new", sort_at=sort_at)
    mp3 = f"{item_id.replace(':', '_')}.mp3"
    ctx.settings.feed_dir.mkdir(parents=True, exist_ok=True)
    (ctx.settings.feed_dir / mp3).write_bytes(b"0123456789")
    store.update(ctx.db, item_id, status="done", mp3=mp3, bytes=10, seconds=61.4, published_at=published_at,
                 episode_title=title, description="Saved on Hacker News.")


def test_feed_is_valid_rss_newest_first(ctx):
    _publish(ctx, "hn:1", 100.0, time.time())
    _publish(ctx, "hn:2", 300.0, time.time())
    path = write_feed(ctx.db, ctx.settings.feed_dir, ctx.settings.base_url)
    channel = ET.parse(path).getroot().find("channel")
    items = channel.findall("item")
    assert [i.findtext("guid") for i in items] == ["hn:2", "hn:1"]
    assert items[0].findtext("title") == "A & B <test>"
    assert items[0].find("enclosure").get("url") == "http://100.1.2.3:8765/hn_2.mp3"
    itunes = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    assert channel.find(f"{itunes}image").get("href") == "http://100.1.2.3:8765/cover.png"
    assert (ctx.settings.feed_dir / "cover.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_retention_deletes_old_audio_but_keeps_the_record(ctx):
    _publish(ctx, "hn:1", 100.0, time.time() - 31 * 86400)
    _publish(ctx, "hn:2", 200.0, time.time())
    assert retention.expire(ctx.db, ctx.settings.feed_dir, 30) == 1
    assert store.get(ctx.db, "hn:1")["status"] == "expired"
    assert not (ctx.settings.feed_dir / "hn_1.mp3").exists()
    assert (ctx.settings.feed_dir / "hn_2.mp3").exists()


@pytest.mark.parametrize("header,expected", [
    (None, None), ("bytes=0-3", (0, 3)), ("bytes=5-", (5, 9)), ("bytes=-4", (6, 9)),
    ("bytes=8-100", (8, 9)), ("bytes=0-1,4-5", None),
])
def test_parse_range(header, expected):
    assert parse_range(header, 10) == expected


def test_parse_range_unsatisfiable():
    with pytest.raises(ValueError):
        parse_range("bytes=10-", 10)


def test_server_resumes_partial_downloads(tmp_path):
    (tmp_path / "ep.mp3").write_bytes(bytes(range(100)))
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{base}/ep.mp3", headers={"Range": "bytes=90-"})) as resp:
            assert resp.status == 206
            assert resp.headers["Content-Range"] == "bytes 90-99/100"
            assert resp.read() == bytes(range(90, 100))
        with urllib.request.urlopen(f"{base}/ep.mp3") as resp:
            assert resp.status == 200 and len(resp.read()) == 100
        for bad in ("/../secret.mp3", "/missing.mp3", "/earmark.db"):
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(f"{base}{bad}")
            assert err.value.code == 404
    finally:
        server.shutdown()
