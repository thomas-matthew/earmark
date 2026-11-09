"""Hacker News favorites (S4): the public favorites pages, item details from the official API and
full comment threads from Algolia. No login needed."""
import re
import time
import urllib.parse

from ..common import web
from ..storage.db import Item
from .base import Context, strip_html

NAME = "hn"
LABEL = "Hacker News"
FILTERED = False
MAX_PAGES = 20
AGENT = {"User-Agent": "earmark/0.1 (personal podcast feed)"}
ALGOLIA = "https://hn.algolia.com/api/v1/items"
FIREBASE = "https://hacker-news.firebaseio.com/v0/item"


def favorite_ids(markup: str) -> list[int]:
    return [int(i) for i in re.findall(r"""<tr class=['"]athing[^'"]*['"] id=['"](\d+)['"]""", markup)]


def _favorites(user: str, comments: bool, known: set[str], first_run: bool) -> list[int]:
    ids: list[int] = []
    for page in range(1, MAX_PAGES + 1):
        query = {"id": user, "p": page, **({"comments": "t"} if comments else {})}
        markup = web.get_text(f"https://news.ycombinator.com/favorites?{urllib.parse.urlencode(query)}", AGENT)
        found = favorite_ids(markup)
        ids += found
        if not found or "morelink" not in markup:
            break
        if not first_run and any(f"{NAME}:{i}" in known for i in found):
            break  # favorites are newest first, so everything further back is already known
        time.sleep(1)
    return ids


def fetch(ctx: Context, known: set[str], first_run: bool) -> list[Item]:
    user = ctx.settings.secret("HN_USERNAME")
    if not user:
        return []
    items = []
    for comments in (False, True):
        for number in _favorites(user, comments, known, first_run):
            item_id = f"{NAME}:{number}"
            if item_id in known:
                continue
            data = web.get_json(f"{FIREBASE}/{number}.json")
            if not data or data.get("deleted") or data.get("dead"):
                continue
            url = f"https://news.ycombinator.com/item?id={number}"
            if data.get("type") == "comment":
                story_id = web.get_json(f"{ALGOLIA}/{number}").get("story_id")
                story = web.get_json(f"{FIREBASE}/{story_id}.json") if story_id else {}
                items.append(Item(item_id, NAME, "comment", f"Comment on: {story.get('title', 'a Hacker News story')}",
                                  url, float(data["time"]), link=story.get("url"), payload={"story_id": story_id}))
            else:
                items.append(Item(item_id, NAME, "story", data.get("title") or f"Story {number}",
                                  url, float(data["time"]), link=data.get("url")))
    return items


def thread_lines(node: dict, depth: int = 0) -> list[str]:
    lines = []
    for child in node.get("children", []):
        if child.get("text"):
            lines.append(f"{'  ' * depth}[comment {child['id']} by {child.get('author')}] {strip_html(child['text'])}")
        lines += thread_lines(child, depth + 1)
    return lines


def material(ctx: Context, row) -> str:
    number = row["id"].split(":", 1)[1]
    if row["kind"] == "comment":
        comment = web.get_json(f"{ALGOLIA}/{number}")
        story = web.get_json(f"{ALGOLIA}/{comment['story_id']}")
        return (f"Hacker News story: {story.get('title')}\nLink: {story.get('url')}\n"
                f"<post>\n{strip_html(story.get('text'))}\n</post>\n\n"
                f"SAVED COMMENT, the focus of this episode, by {comment.get('author')}:\n"
                f"<saved_comment>\n{strip_html(comment.get('text'))}\n</saved_comment>\n\n"
                "<replies_to_saved_comment>\n" + "\n".join(thread_lines(comment)) + "\n</replies_to_saved_comment>\n\n"
                "<whole_discussion>\n" + "\n".join(thread_lines(story)) + "\n</whole_discussion>")
    story = web.get_json(f"{ALGOLIA}/{number}")
    return (f"Hacker News story: {story.get('title')}\nLink: {story.get('url')}\nPoints: {story.get('points')}\n"
            f"<post>\n{strip_html(story.get('text'))}\n</post>\n\n"
            "<discussion>\n" + "\n".join(thread_lines(story)) + "\n</discussion>")
