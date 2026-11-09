"""E4: read my Reddit saved items with my own session cookie, plus one full thread.

Needs REDDIT_SESSION and REDDIT_USERNAME in ../.env. Makes two read-only requests.
Usage (from experiments/): uv run python reddit_probe.py
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def env(name: str) -> str:
    match = re.search(rf"^{name}=(.+)$", ENV_FILE.read_text(), re.M)
    if not match:
        raise SystemExit(f"{name} is missing from .env")
    return match.group(1).strip().strip("\"'")


def get(path: str, cookie: str) -> tuple[int, str]:
    request = urllib.request.Request(
        f"https://www.reddit.com{path}",
        headers={"User-Agent": AGENT, "Accept": "application/json", "Cookie": f"reddit_session={cookie}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def count_comments(listing: list) -> tuple[int, int]:
    total, chars = 0, 0
    for child in listing:
        if child.get("kind") != "t1":
            continue
        total += 1
        chars += len(child["data"].get("body", ""))
        replies = child["data"].get("replies")
        if replies:
            sub_total, sub_chars = count_comments(replies["data"]["children"])
            total, chars = total + sub_total, chars + sub_chars
    return total, chars


def main() -> None:
    cookie, user = env("REDDIT_SESSION"), urllib.parse.quote(env("REDDIT_USERNAME"))
    status, body = get(f"/user/{user}/saved.json?limit=25&raw_json=1", cookie)
    print(f"saved list: status {status}, json: {body.lstrip().startswith('{')}")
    if status != 200 or not body.lstrip().startswith("{"):
        print(re.sub(r"\s+", " ", body)[:160])
        return
    data = json.loads(body)["data"]
    items = data["children"]
    print(f"items returned: {len(items)}, more pages: {bool(data.get('after'))}")
    for item in items[:10]:
        d = item["data"]
        kind = "post" if item["kind"] == "t3" else "comment"
        label = d.get("title") or d.get("link_title") or ""
        print(f"  {d['name']} {kind:7} r/{d.get('subreddit')}  {label[:60]}  link: {str(d.get('url') or '')[:50]}")

    posts = [i["data"] for i in items if i["kind"] == "t3"]
    if posts:
        time.sleep(2)
        status, body = get(f"{posts[0]['permalink']}.json?limit=500&raw_json=1", cookie)
        print(f"\nthread: status {status}")
        if status == 200:
            thread = json.loads(body)
            total, chars = count_comments(thread[1]["data"]["children"])
            print(f"post text {len(thread[0]['data']['children'][0]['data'].get('selftext', ''))} chars, "
                  f"comments {total}, comment text {chars} chars")


if __name__ == "__main__":
    main()
