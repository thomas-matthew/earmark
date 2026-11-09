"""E7: can a user's public Hacker News favorites be listed and read in full?

Usage: uv run python hn_probe.py USERNAME
"""
import html
import json
import re
import sys
import urllib.request

import trafilatura

AGENT = {"User-Agent": "bookcast-experiment/0.1"}
CHARS_PER_MINUTE = 8768 / 10.4  # measured from the Kokoro sample


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def favorites(user: str, comments: bool = False) -> list[str]:
    url = f"https://news.ycombinator.com/favorites?id={user}" + ("&comments=t" if comments else "")
    return re.findall(r"""<tr class=['"]athing[^'"]*['"] id=['"](\d+)['"]""", get(url))


def strip(markup: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", markup or "")).strip()


def walk(node: dict, depth: int = 0):
    for child in node.get("children", []):
        if child.get("text"):
            yield depth, child.get("author"), strip(child["text"])
        yield from walk(child, depth + 1)


def main(user: str) -> None:
    stories, comments = favorites(user), favorites(user, comments=True)
    print(f"favorite stories: {stories}\nfavorite comments: {comments}")
    for story_id in stories:
        item = json.loads(get(f"https://hn.algolia.com/api/v1/items/{story_id}"))
        thread = list(walk(item))
        thread_chars = sum(len(text) for _, _, text in thread)
        print(f"\n{item.get('title')}\n  link: {item.get('url') or '(discussion only)'}")
        print(f"  post text chars: {len(strip(item.get('text')))}")
        print(f"  comments: {len(thread)} ({sum(d == 0 for d, _, _ in thread)} top-level), "
              f"deepest reply level {max((d for d, _, _ in thread), default=0)}, {thread_chars} chars, "
              f"about {thread_chars / CHARS_PER_MINUTE:.0f} min of audio")
        if item.get("url"):
            page = trafilatura.fetch_url(item["url"])
            doc = trafilatura.bare_extraction(page, url=item["url"], with_metadata=True) if page else None
            chars = len(doc.text or "") if doc else 0
            print(f"  article: {chars} chars, about {chars / CHARS_PER_MINUTE:.0f} min, title: {getattr(doc, 'title', None)!r}")


if __name__ == "__main__":
    main(sys.argv[1])
