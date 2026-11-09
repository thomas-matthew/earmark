"""Tests for the parts that don't need X credentials or the voice model."""
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

os.environ["BOOKCAST_DATA"] = tempfile.mkdtemp()
import bookcast  # noqa: E402

USERS = {"1": "alice"}


def tweet(tweet_id, text="hello", urls=None, note=None):
    t = {"id": tweet_id, "author_id": "1", "text": text}
    if urls:
        t["entities"] = {"urls": [{"expanded_url": u} for u in urls]}
    if note:
        t["note_tweet"] = note
    return t


class ParseTweet(unittest.TestCase):
    def test_external_link_is_read(self):
        self.assertEqual(
            bookcast.parse_tweet(tweet("9", urls=["https://blog.example/a"]), USERS)[1],
            "https://blog.example/a",
        )

    def test_quote_link_to_x_falls_back_to_post(self):
        self.assertEqual(
            bookcast.parse_tweet(tweet("9", urls=["https://x.com/b/status/2"]), USERS)[1],
            "https://x.com/alice/status/9",
        )

    def test_long_post_uses_note_text(self):
        self.assertEqual(bookcast.parse_tweet(tweet("9", "short…", note={"text": "the whole post"}), USERS)[2], "the whole post")


class SyncX(unittest.TestCase):
    def setUp(self):
        bookcast.DB_PATH.unlink(missing_ok=True)
        bookcast.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        bookcast.TOKEN_PATH.write_text("{}")
        self.db = bookcast.connect()

    def sync(self, *tweets):
        page = {"data": list(tweets), "includes": {"users": [{"id": "1", "username": "alice"}]}, "meta": {}}
        with mock.patch.object(bookcast, "x_get", side_effect=lambda path, *_: {"data": {"id": "1"}} if path == "/users/me" else page):
            bookcast.sync_x(self.db)

    def statuses(self):
        return dict(self.db.execute("SELECT id, status FROM items").fetchall())

    def test_first_run_queues_nothing_then_only_new_items(self):
        self.sync(tweet("1"), tweet("2"))
        self.assertEqual(self.statuses(), {"x:1": "baseline", "x:2": "baseline"})
        self.sync(tweet("3"), tweet("1"))
        self.assertEqual(self.statuses(), {"x:1": "baseline", "x:2": "baseline", "x:3": "pending"})


class Feed(unittest.TestCase):
    def test_special_characters_stay_valid_xml(self):
        bookcast.DB_PATH.unlink(missing_ok=True)
        db = bookcast.connect()
        db.execute(
            "INSERT INTO items (id,source,url,status,title,mp3,bytes,seconds,added_at,published_at) "
            "VALUES ('a','X','https://e.com/?a=1&b=2','done','Q&A <live>','f.mp3',10,61.2,1,1)"
        )
        item = ET.parse(bookcast.write_feed(db)).getroot().find("channel/item")
        self.assertEqual(item.findtext("title"), "Q&A <live>")
        self.assertTrue(item.find("enclosure").get("url").endswith("/f.mp3"))


class Script(unittest.TestCase):
    def test_unreadable_link_is_announced_not_dropped(self):
        with mock.patch.object(bookcast, "extract", return_value=(None, None)):
            title, script, note = bookcast.build_script({"url": "https://paywall.example/a", "post_text": "", "source": "X"})
        self.assertIn("could not be read", script)
        self.assertTrue(note)


if __name__ == "__main__":
    unittest.main()
