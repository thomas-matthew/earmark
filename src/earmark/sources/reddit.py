"""Reddit saved items (S2) through the website's JSON endpoints and my session cookie.
Reddit's official app route is closed to new personal apps, so this is unofficial (see Known risks)."""
import json
import time
import urllib.parse

from ..common import web
from ..common.web import LoginExpired
from ..storage.db import Item
from .base import Context

NAME = "reddit"
LABEL = "Reddit"
FILTERED = True
MAX_PAGES = 10  # Reddit lists at most 1000 saved items


def _get(ctx: Context, path: str) -> dict | list:
    cookie = ctx.settings.secret("REDDIT_SESSION")
    if not cookie:
        raise LoginExpired(LABEL)
    status, body, _ = web.request(f"https://www.reddit.com{path}",
                                  {"Accept": "application/json", "Cookie": f"reddit_session={cookie}"})
    if status in (401, 403) or (status == 200 and not body.lstrip().startswith((b"{", b"["))):
        raise LoginExpired(LABEL)
    if status != 200:
        raise web.HttpError(status, f"https://www.reddit.com{path}")
    return json.loads(body)


def to_item(child: dict) -> Item:
    d = child["data"]
    if child["kind"] == "t1":
        link = d.get("link_url")
        own_thread = "reddit.com" in urllib.parse.urlparse(link or "").netloc
        return Item(f"{NAME}:{d['name']}", NAME, "comment", f"Comment on: {d.get('link_title', '')}",
                    f"https://www.reddit.com{d['permalink']}", float(d["created_utc"]),
                    link=None if own_thread else link,
                    payload={"subreddit": d.get("subreddit"), "thread": urllib.parse.urlparse(d["link_permalink"]).path})
    return Item(f"{NAME}:{d['name']}", NAME, "post", d.get("title", ""), f"https://www.reddit.com{d['permalink']}",
                float(d["created_utc"]), link=None if d.get("is_self") else d.get("url"),
                payload={"subreddit": d.get("subreddit"), "thread": d["permalink"]})


def fetch(ctx: Context, known: set[str], first_run: bool) -> list[Item]:
    user = ctx.settings.secret("REDDIT_USERNAME")
    if not user:
        return []
    items, after = [], None
    for _ in range(MAX_PAGES):
        query = {"limit": 100, "raw_json": 1, **({"after": after} if after else {})}
        data = _get(ctx, f"/user/{urllib.parse.quote(user)}/saved.json?{urllib.parse.urlencode(query)}")["data"]
        page = [to_item(c) for c in data["children"] if c["kind"] in ("t1", "t3")]
        items += [i for i in page if i.id not in known]
        after = data.get("after")
        if not after or (not first_run and any(i.id in known for i in page)):
            break
        time.sleep(2)  # keep requests slow and polite
    return items


def _comments(children: list, depth: int = 0) -> list[str]:
    lines = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        d = child["data"]
        lines.append(f"{'  ' * depth}[comment {d['name']} score {d.get('score')}] {d.get('body', '')}")
        replies = d.get("replies")
        if replies:
            lines += _comments(replies["data"]["children"], depth + 1)
    return lines


def material(ctx: Context, row) -> str:
    payload = json.loads(row["payload"])
    post_listing, comment_listing = _get(ctx, f"{payload['thread'].rstrip('/')}.json?limit=500&raw_json=1")
    post = post_listing["data"]["children"][0]["data"]
    focus = ""
    if row["kind"] == "comment":
        name = row["id"].split(":", 1)[1]
        comment = _get(ctx, f"{payload['thread'].rstrip('/')}/{name.removeprefix('t1_')}.json?limit=500&raw_json=1")[1]
        saved = comment["data"]["children"][0]["data"]
        focus = (f"SAVED COMMENT, the focus of this episode:\n<saved_comment>\n{saved.get('body', '')}\n</saved_comment>\n"
                 "<replies_to_saved_comment>\n" + "\n".join(_comments((saved.get("replies") or {"data": {"children": []}})["data"]["children"]))
                 + "\n</replies_to_saved_comment>\n\n")
    return (f"Subreddit: r/{post.get('subreddit')}\nTitle: {post.get('title')}\nScore: {post.get('score')}\n"
            f"Link: {None if post.get('is_self') else post.get('url')}\n\n{focus}"
            f"<post>\n{post.get('selftext', '')}\n</post>\n\n<discussion>\n"
            + "\n".join(_comments(comment_listing["data"]["children"])) + "\n</discussion>")
