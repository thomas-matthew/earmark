"""Substack likes (S3, added 2026-11-15): posts and Notes I liked, read from the Likes tab of my own
Substack profile through the same unofficial reader API and session cookie as saved posts.

Liking replaced saving for me once Substack moved the save button out of the main view. Likes have
their own first run, so likes older than the look-back window are recorded without episodes.
A liked post becomes the same item as a saved one (substack:<post id>); a liked Note becomes an
item of its own with its text, images, any post it shares and the comments it replies to."""
import json
import urllib.parse

from ..storage import db as store
from ..storage.db import Item
from . import substack
from .base import Context

NAME = "substack_likes"
LABEL = "Substack"
LOG_LABEL = "Substack likes"
SAVED_VERB = "liked"
FILTERED = False
SELF = "https://substack.com/api/v1/user/profile/self"
LIKES = "https://substack.com/api/v1/reader/feed/profile/{user}?types=like"
MAX_PAGES = 25
MAX_TITLE = 80


def _links(node) -> list[str]:
    """Link targets inside a Note's rich-text body."""
    found = []
    if isinstance(node, dict):
        for mark in node.get("marks") or []:
            href = (mark.get("attrs") or {}).get("href")
            if mark.get("type") == "link" and href and href not in found:
                found.append(href)
        for child in node.get("content") or []:
            found += [h for h in _links(child) if h not in found]
    return found


def note_item(entry: dict) -> Item:
    note = entry["comment"]
    body = (note.get("body") or "").strip()
    images, posts, links = [], [], _links(note.get("body_json"))
    for attachment in note.get("attachments") or []:
        if attachment.get("type") == "image" and attachment.get("imageUrl"):
            images.append(attachment["imageUrl"])
        elif attachment.get("type") == "post" and (attachment.get("post") or {}).get("canonical_url"):
            post = attachment["post"]
            posts.append({"title": post.get("title"), "url": post["canonical_url"],
                          "paywalled": post.get("audience") not in (None, "everyone")})
        elif (attachment.get("linkMetadata") or {}).get("url"):
            links.append(attachment["linkMetadata"]["url"])
    handle = note.get("handle") or "unknown"
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    title = f"Note by {note.get('name') or handle}" + (f": {first_line}" if first_line else "")
    if len(title) > MAX_TITLE:
        title = title[:MAX_TITLE - 1].rstrip() + "…"
    link = posts[0]["url"] if posts else (links[0] if links else None)
    return Item(
        f"{substack.NAME}:c-{note['id']}", NAME, "note", title,
        f"https://substack.com/@{handle}/note/c-{note['id']}", substack.timestamp(entry["context"]["timestamp"]),
        link=link,
        payload={
            "author": note.get("name"), "handle": handle, "body": body, "posted": note.get("date"),
            "images": images, "posts": posts, "links": links,
            "parents": [{"handle": c.get("handle"), "body": c.get("body")} for c in entry.get("parentComments") or []],
        },
    )


def to_item(entry: dict) -> Item | None:
    when = (entry.get("context") or {}).get("timestamp")
    if not when:
        return None
    if entry.get("type") == "post" and entry.get("post"):
        publication = entry.get("publication") or {}
        return substack.to_item(entry["post"], {entry["post"].get("publication_id"): publication.get("name")}, NAME, when)
    if entry.get("type") == "comment" and entry.get("comment"):
        return note_item(entry)
    return None


def fetch(ctx: Context, known: set[str], first_run: bool) -> list[Item]:
    known = known | store.known_ids(ctx.db, substack.NAME)  # liked posts that were also saved
    user = substack.get_json(ctx, SELF)["id"]
    items, cursor = [], None
    for _ in range(MAX_PAGES):
        url = LIKES.format(user=user) + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        data = substack.get_json(ctx, url)
        page = [i for i in map(to_item, data.get("items") or []) if i]
        items += [i for i in page if i.id not in known and i.id not in {x.id for x in items}]
        cursor = data.get("nextCursor")
        if not cursor or (not first_run and any(i.id in known for i in page)):
            break
    return items


def material(ctx: Context, row) -> str:
    if row["kind"] != "note":
        return substack.material(ctx, row)
    payload = json.loads(row["payload"])
    lines = [f"Substack Note by {payload.get('author')} (@{payload.get('handle')}), posted {payload.get('posted')}",
             f"Link: {row['url']}"]
    for parent in payload.get("parents") or []:
        lines.append(f"<replying_to by=@{parent.get('handle')}>\n{parent.get('body')}\n</replying_to>")
    lines.append(f"<note>\n{payload.get('body')}\n</note>")
    if payload.get("images"):
        lines.append("Images in the note. Look at them with view_image; they often carry the main content:")
        lines += [f"{i + 1}. {url}" for i, url in enumerate(payload["images"])]
    for post in payload.get("posts") or []:
        lines.append(f"The note shares this Substack post: {post.get('title')} ({post['url']}). Read it with fetch_page."
                     + (" It is for paid subscribers; only its free preview is public. Say so in the episode." if post.get("paywalled") else ""))
    if payload.get("links"):
        lines.append("Links in the note (read the ones that matter with fetch_page): " + ", ".join(payload["links"]))
    return "\n".join(lines)
