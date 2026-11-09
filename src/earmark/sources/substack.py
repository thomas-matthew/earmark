"""Substack saved posts (S3) through the reader's unofficial endpoint and my session cookie.
Post text comes from the public page, so paywalled posts give only their free preview (C4)."""
import json
import urllib.parse
from datetime import datetime

from ..common import web
from ..common.web import LoginExpired
from ..storage.db import Item
from .base import Context

NAME = "substack"
LABEL = "Substack"
FILTERED = False
API = "https://substack.com/api/v1/reader/posts?inboxType=saved&limit=20"
MAX_PAGES = 25


def _page(ctx: Context, cursor: str | None) -> dict:
    sid = ctx.settings.secret("SUBSTACK_SID")
    if not sid:
        raise LoginExpired(LABEL)
    url = API + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
    status, body, _ = web.request(url, {"Accept": "application/json", "Cookie": f"substack.sid={sid}"})
    if status in (401, 403):
        raise LoginExpired(LABEL)
    if status != 200:
        raise web.HttpError(status, url)
    return json.loads(body)


def to_item(post: dict, publications: dict) -> Item:
    authors = [b.get("name") for b in post.get("publishedBylines") or [] if b.get("name")]
    return Item(
        f"{NAME}:{post['id']}", NAME, "podcast" if post.get("podcast_url") else "article", post.get("title") or "Untitled",
        post["canonical_url"], datetime.fromisoformat(post["saved_at"].replace("Z", "+00:00")).timestamp(),
        link=post["canonical_url"],
        payload={
            "publication": publications.get(post.get("publication_id")),
            "authors": authors,
            "subtitle": post.get("subtitle"),
            "paywalled": post.get("audience") not in (None, "everyone"),
            "wordcount": post.get("wordcount"),
            "podcast_url": post.get("podcast_url"),
            "posted": post.get("post_date"),
        },
    )


def fetch(ctx: Context, known: set[str], first_run: bool) -> list[Item]:
    items, cursor = [], None
    for _ in range(MAX_PAGES):
        data = _page(ctx, cursor)
        publications = {p["id"]: p.get("name") for p in data.get("publications") or []}
        page = [to_item(p, publications) for p in data.get("posts") or []]
        items += [i for i in page if i.id not in known]
        cursor = data.get("cursor")
        if not data.get("more") or not cursor or (not first_run and any(i.id in known for i in page)):
            break
    return items


def material(ctx: Context, row) -> str:
    payload = json.loads(row["payload"])
    lines = [f"Substack post: {row['title']}", f"Publication: {payload.get('publication')}",
             f"Authors: {', '.join(payload.get('authors') or []) or 'unknown'}", f"Link: {row['url']}"]
    if payload.get("subtitle"):
        lines.append(f"Subtitle: {payload['subtitle']}")
    if payload.get("paywalled"):
        lines.append("This post is for paid subscribers; only its free preview is public. Say in the episode that it is a preview.")
    lines.append("Read the post itself with fetch_page on its link.")
    return "\n".join(lines)
