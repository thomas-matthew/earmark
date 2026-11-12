import json
import time

import pytest

from earmark import pipeline, sources
from earmark.content.media import is_media_link
from earmark.storage import db as store
from earmark.storage.db import Item
from earmark.sources import hn, reddit, substack, x


def test_x_bookmark_with_article_and_external_link():
    tweet = {
        "id": "10", "author_id": "u1", "created_at": "2026-11-01T10:00:00.000Z", "conversation_id": "10",
        "text": "short", "note_tweet": {"text": "the long version", "entities": {"urls": [
            {"expanded_url": "https://x.com/i/article/1"}, {"expanded_url": "https://example.com/paper"}]}},
        "article": {"title": "My Article", "plain_text": "Full article text."},
        "referenced_tweets": [{"type": "quoted", "id": "9"}],
    }
    item = x.to_item(tweet, {"u1": "alice"}, {"9": {"id": "9", "text": "quoted words"}})
    assert item.id == "x:10" and item.kind == "article" and item.title == "My Article"
    assert item.url == "https://x.com/alice/status/10"
    assert item.link == "https://example.com/paper"
    assert item.payload["text"] == "the long version" and item.payload["quoted"] == ["quoted words"]


def test_x_short_links_are_expanded_and_linked_posts_found():
    reply = {"id": "11", "text": "more: https://t.co/aaa and https://t.co/bbb", "entities": {"urls": [
        {"url": "https://t.co/aaa", "expanded_url": "https://x.com/bob/status/77?s=20"},
        {"url": "https://t.co/bbb", "expanded_url": "https://site.dev", "unwound_url": "https://site.dev/home"}]}}
    text = x._text(reply)
    assert text == "more: https://x.com/bob/status/77?s=20 and https://site.dev/home"
    assert x.linked_posts([text, "see https://twitter.com/carol/status/88 and x.com/bob/status/77"], skip={"88"}) == ["77"]


def test_x_enrich_fetches_thread_and_linked_posts(ctx, monkeypatch):
    calls = []

    def fake_get(_ctx, path, params=None):
        calls.append(path)
        if path == "/tweets/search/recent":
            return {"data": [{"id": "11", "created_at": "2", "text": "part two https://t.co/a",
                              "entities": {"urls": [{"url": "https://t.co/a", "expanded_url": "https://x.com/me/status/50"}]}}]}
        if path == "/tweets":
            assert params["ids"] == "50"
            return {"data": [{"id": "50", "author_id": "u1", "text": "what the site is"}],
                    "includes": {"users": [{"id": "u1", "username": "me"}]}}
        raise AssertionError(path)

    monkeypatch.setattr(x.api, "get", fake_get)
    item = Item("x:10", "x", "post", "t", "u", 0.0, payload={"author": "me", "conversation_id": "10", "text": "look"})
    x.enrich(ctx, item)
    assert item.payload["thread"] == ["part two https://x.com/me/status/50"]
    assert item.payload["linked"] == [{"author": "me", "text": "what the site is"}]
    material = x.material(ctx, {"payload": json.dumps(item.payload), "link": None})
    assert "<linked_x_post by=@me>\nwhat the site is" in material


def test_tiny_refresh_pages_are_followed_and_script_pages_use_the_browser():
    from earmark.content.extract import Page, needs_browser, refresh_target

    tco = b'<head><meta name="referrer" content="always"><noscript><META http-equiv="refresh" content="0;URL=https://site.dev/a?x=1&amp;y=2"></noscript></head>'
    assert refresh_target(tco, "text/html", "https://t.co/z") == "https://site.dev/a?x=1&y=2"
    assert refresh_target(b'<script>location.replace("https:\\/\\/site.dev\\/b")</script>', "text/html", "https://t.co/z") == "https://site.dev/b"
    assert refresh_target(tco + b" " * 5000, "text/html", "https://t.co/z") is None  # a real page, not a notice
    assert needs_browser("<script src=app.js></script>", Page("u", None, "This site needs JavaScript to run."))
    assert not needs_browser("<script></script>", Page("u", None, "word " * 200))
    assert not needs_browser("<p>short</p>", Page("u", None, "short"))


def test_reddit_saved_comment_points_at_its_thread():
    child = {"kind": "t1", "data": {"name": "t1_abc", "link_title": "A post", "permalink": "/r/s/comments/p1/a_post/abc/",
                                    "link_permalink": "https://www.reddit.com/r/s/comments/p1/a_post/",
                                    "link_url": "https://www.reddit.com/r/s/comments/p1/a_post/", "created_utc": 1.0,
                                    "subreddit": "s"}}
    item = reddit.to_item(child)
    assert item.id == "reddit:t1_abc" and item.kind == "comment" and item.link is None
    assert item.payload["thread"] == "/r/s/comments/p1/a_post/"


def test_substack_paywalled_and_podcast_posts():
    post = {"id": 5, "title": "T", "canonical_url": "https://a.substack.com/p/t", "saved_at": "2026-10-30T23:25:18.838Z",
            "audience": "only_paid", "podcast_url": "https://cdn.example.com/ep.mp3", "publication_id": 7,
            "publishedBylines": [{"name": "Ann"}]}
    item = substack.to_item(post, {7: "A Letter"})
    assert item.kind == "podcast" and item.payload["paywalled"] and item.payload["publication"] == "A Letter"


def test_hn_favorite_ids_from_markup():
    markup = "<tr class='athing submission' id='123'><tr class=\"athing comtr\" id=\"456\">"
    assert hn.favorite_ids(markup) == [123, 456]


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=abc", True), ("https://youtu.be/abc", True),
    ("https://www.youtube.com/@channel", False), ("https://vimeo.com/123", True),
    ("https://example.com/watch", False), (None, False),
])
def test_media_links(url, expected):
    assert is_media_link(url) is expected


class FakeSource:
    def __init__(self, name, items):
        self.NAME, self.LABEL, self.FILTERED, self.items, self.calls = name, name, False, items, []

    def fetch(self, ctx, known, first_run):
        self.calls.append(first_run)
        return [i for i in self.items if i.id not in known]


def _with_sources(monkeypatch, *fakes):
    monkeypatch.setattr(sources, "ALL", list(fakes))
    monkeypatch.setattr(sources, "BY_NAME", {f.NAME: f for f in fakes})


def test_first_run_looks_back_two_months_when_one_month_is_thin(ctx, monkeypatch):
    now = time.time()
    items = [Item(f"a:{d}", "a", "post", f"{d} days", "u", now - d * 86400) for d in (1, 20, 45, 90)]
    fake = FakeSource("a", items)
    _with_sources(monkeypatch, fake)
    pipeline.sync(ctx, ctx.settings, pipeline.Report())
    statuses = {r["id"]: r["status"] for r in ctx.db.execute("SELECT id, status FROM items")}
    assert statuses == {"a:1": "new", "a:20": "new", "a:45": "new", "a:90": "baseline"}
    assert store.meta_get(ctx.db, "lookback_days") == "60"

    fake.items.append(Item("a:old-but-new", "a", "post", "saved today", "u", now - 400 * 86400))
    pipeline.sync(ctx, ctx.settings, pipeline.Report())
    assert fake.calls == [True, False]
    assert store.get(ctx.db, "a:old-but-new")["status"] == "new"  # after the first run every new save counts


def test_one_month_is_enough_when_it_has_ten_items(ctx, monkeypatch):
    now = time.time()
    items = [Item(f"a:{d}", "a", "post", "t", "u", now - d * 86400) for d in list(range(10)) + [45]]
    _with_sources(monkeypatch, FakeSource("a", items))
    pipeline.sync(ctx, ctx.settings, pipeline.Report())
    assert store.get(ctx.db, "a:45")["status"] == "baseline"


def test_a_failing_source_does_not_stop_the_others(ctx, monkeypatch):
    class Broken(FakeSource):
        def fetch(self, ctx, known, first_run):
            from earmark.common.web import LoginExpired
            raise LoginExpired("Broken")

    _with_sources(monkeypatch, Broken("b", []), FakeSource("a", [Item("a:1", "a", "post", "t", "u", time.time())]))
    report = pipeline.Report()
    pipeline.sync(ctx, ctx.settings, report)
    assert report.found == 1 and report.failures == ["Broken login is no longer accepted"]
    assert store.meta_get(ctx.db, "synced:b") is None  # its first run happens once the login works again
