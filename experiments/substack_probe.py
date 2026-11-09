"""E5: read Substack saved posts outside a browser and test article extraction.

Usage (from experiments/):
  uv run python substack_probe.py extract URL [URL...]   # public page extraction only
  uv run python substack_probe.py saved                  # needs SUBSTACK_SID in ../.env
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import trafilatura

API = "https://substack.com/api/v1/reader/posts?inboxType=saved&limit=20"
AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def session_cookie() -> str | None:
    if not ENV_FILE.exists():
        return None
    match = re.search(r"^SUBSTACK_SID=(.+)$", ENV_FILE.read_text(), re.M)
    return match.group(1).strip().strip("\"'") if match else None


def fetch_saved(cookie: str | None) -> tuple[int, str]:
    headers = {"User-Agent": AGENT, "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = f"substack.sid={cookie}"
    try:
        with urllib.request.urlopen(urllib.request.Request(API, headers=headers), timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def saved() -> None:
    cookie = session_cookie()
    status, body = fetch_saved(cookie)
    print(f"cookie supplied: {bool(cookie)}, status {status}, cloudflare challenge: {'cf-chl' in body or 'Just a moment' in body}")
    if status != 200:
        print(body[:150])
        return
    data = json.loads(body)
    print(f"saved posts: {len(data['posts'])}, more: {data.get('more')}")
    for post in data["posts"]:
        print(f"  {post['id']} {post['saved_at'][:10]} {post['audience']:12} {post['wordcount']:6} words  {post['title'][:60]}")


def extract(urls: list[str]) -> None:
    for url in urls:
        page = trafilatura.fetch_url(url)
        doc = trafilatura.bare_extraction(page, url=url, with_metadata=True) if page else None
        text = (doc.text or "") if doc else ""
        print(f"{len(text.split()):6} words  {doc.title if doc else 'FAILED'}\n        {url}\n        ends: ...{text[-90:]!r}")


if __name__ == "__main__":
    if sys.argv[1] == "saved":
        saved()
    else:
        extract(sys.argv[2:])
