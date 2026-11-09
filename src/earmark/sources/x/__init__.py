"""X bookmarks (S1) through the official API, including X Article full text and the author's
thread (C2b). Threads are only searchable for about a week, so they are fetched as soon as an item is found."""
import json
import time
import urllib.parse
from datetime import datetime

from ...storage import db as store
from ...storage.db import Item
from ..base import Context
from . import api

NAME = "x"
LABEL = "X"
FILTERED = True
TWEET_FIELDS = "note_tweet,entities,conversation_id,created_at,referenced_tweets,article,author_id"
OWN_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "t.co", "mobile.twitter.com"}
FIRST_RUN_PAGES, LATER_PAGES = 5, 3
MAX_LOOKBACK_DAYS = 62


def _date(value: str | None) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else time.time()


def _text(tweet: dict) -> str:
    return (tweet.get("note_tweet") or {}).get("text") or tweet.get("text", "")


def external_link(tweet: dict) -> str | None:
    entities = (tweet.get("note_tweet") or {}).get("entities") or tweet.get("entities") or {}
    for link in entities.get("urls", []):
        expanded = link.get("unwound_url") or link.get("expanded_url") or ""
        host = (urllib.parse.urlparse(expanded).hostname or "").lower()
        if expanded and host not in OWN_HOSTS:
            return expanded
    return None


def to_item(tweet: dict, users: dict, included: dict) -> Item:
    author = users.get(tweet.get("author_id"), "unknown")
    article = tweet.get("article") or {}
    text = _text(tweet)
    quoted = [_text(included[r["id"]]) for r in tweet.get("referenced_tweets") or []
              if r.get("type") == "quoted" and r.get("id") in included]
    title = article.get("title") or " ".join(text.split())[:90] or f"Post by @{author}"
    return Item(
        f"{NAME}:{tweet['id']}", NAME, "article" if article else "post", title,
        f"https://x.com/{author}/status/{tweet['id']}", _date(tweet.get("created_at")),
        link=external_link(tweet),
        payload={"author": author, "author_id": tweet.get("author_id"), "text": text, "quoted": quoted,
                 "conversation_id": tweet.get("conversation_id"),
                 "article_title": article.get("title"), "article_text": article.get("plain_text")},
    )


def fetch(ctx: Context, known: set[str], first_run: bool) -> list[Item]:
    user_id = store.meta_get(ctx.db, "x_user_id")
    if not user_id:
        user_id = api.get(ctx, "/users/me")["data"]["id"]
        store.meta_set(ctx.db, "x_user_id", user_id)
    params = {"max_results": 100 if first_run else 20, "expansions": "author_id,referenced_tweets.id",
              "user.fields": "username", "tweet.fields": TWEET_FIELDS}
    oldest_wanted = time.time() - MAX_LOOKBACK_DAYS * 86400
    items: list[Item] = []
    for _ in range(FIRST_RUN_PAGES if first_run else LATER_PAGES):
        page = api.get(ctx, f"/users/{user_id}/bookmarks", params)
        includes = page.get("includes") or {}
        users = {u["id"]: u["username"] for u in includes.get("users") or []}
        included = {t["id"]: t for t in includes.get("tweets") or []}
        batch = [to_item(t, users, included) for t in page.get("data") or []]
        items += [i for i in batch if i.id not in known]
        token = (page.get("meta") or {}).get("next_token")
        if not token or not batch:
            break
        if not first_run and any(i.id in known for i in batch):
            break
        if first_run and all(i.item_date < oldest_wanted for i in batch):
            break  # every post on this page predates the longest look-back; stop paying for more
        params = {**params, "pagination_token": token}
    return items


def enrich(ctx: Context, item: Item) -> None:
    """Fetch the author's thread while it is still searchable. Called only for items that will be processed."""
    payload = item.payload
    conversation = payload.get("conversation_id")
    if not conversation:
        return
    query = f"conversation_id:{conversation} from:{payload['author']}"
    found = api.get(ctx, "/tweets/search/recent", {"query": query, "max_results": 100,
                                                  "tweet.fields": "note_tweet,created_at"}).get("data") or []
    posts = {t["id"]: t for t in found}
    if conversation != item.id.split(":", 1)[1] and conversation not in posts:
        root = api.get(ctx, f"/tweets/{conversation}", {"tweet.fields": "note_tweet,created_at,author_id"}).get("data")
        if root and root.get("author_id") == payload.get("author_id"):
            posts[root["id"]] = root
    thread = sorted(posts.values(), key=lambda t: t.get("created_at", ""))
    payload["thread"] = [_text(t) for t in thread if t["id"] != item.id.split(":", 1)[1]]


def material(ctx: Context, row) -> str:
    p = json.loads(row["payload"])
    parts = [f"X post by @{p.get('author')}", f"Link in post: {row['link']}", f"<post>\n{p.get('text', '')}\n</post>"]
    for quote in p.get("quoted") or []:
        parts.append(f"<quoted_post>\n{quote}\n</quoted_post>")
    if p.get("thread"):
        parts.append("<author_thread>\n" + "\n---\n".join(p["thread"]) + "\n</author_thread>")
    if p.get("article_text"):
        parts.append(f"<x_article title={p.get('article_title')!r}>\n{p['article_text']}\n</x_article>")
    return "\n\n".join(parts)
