"""E6: read my X bookmarks through the official API, and try to fetch a whole thread.

Needs X_CLIENT_ID (and X_CLIENT_SECRET for a confidential client) in ../.env.
Usage (from experiments/):
  uv run python x_probe.py auth   # opens X in the browser once to approve read access
  uv run python x_probe.py test   # a small number of paid reads
"""
import os
import re
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
for line in ENV_FILE.read_text().splitlines():
    match = re.match(r"^(X_CLIENT_ID|X_CLIENT_SECRET)=(.+)$", line.strip())
    if match:
        os.environ[match.group(1)] = match.group(2).strip().strip("\"'")

import bookcast  # noqa: E402  (reuses the prototype's OAuth flow; token saved in experiments/data/)

FIELDS = {
    "max_results": 10,
    "expansions": "author_id,referenced_tweets.id",
    "user.fields": "username",
    "tweet.fields": "note_tweet,entities,conversation_id,created_at,referenced_tweets,article",
}


def test() -> None:
    me = bookcast.x_get("/users/me")["data"]
    print(f"signed in as @{me['username']}")
    page = bookcast.x_get(f"/users/{me['id']}/bookmarks", FIELDS)
    tweets = page.get("data", [])
    users = {u["id"]: u["username"] for u in page.get("includes", {}).get("users", [])}
    print(f"bookmarks returned: {len(tweets)} (requested 10), more: {bool(page.get('meta', {}).get('next_token'))}")
    for t in tweets:
        item_id, url, text = bookcast.parse_tweet(t, users)
        thread = "thread" if t.get("conversation_id") != t["id"] else "single"
        print(f"  {t['id']} @{users.get(t.get('author_id'), '?'):15} {t.get('created_at', '')[:10]} {thread:6} "
              f"long={bool(t.get('note_tweet'))} article={bool(t.get('article'))} reads:{url[:55]}")

    candidates = [t for t in tweets if t.get("conversation_id")]
    if not candidates:
        return
    target = candidates[0]
    author = users.get(target["author_id"])
    query = f"conversation_id:{target['conversation_id']} from:{author}"
    try:
        result = bookcast.x_get("/tweets/search/recent", {"query": query, "max_results": 50, "tweet.fields": "created_at"})
        print(f"\nthread search for {target['conversation_id']}: {result.get('meta', {}).get('result_count', 0)} posts by the author "
              f"(recent search covers only about the last 7 days)")
    except Exception as exc:  # noqa: BLE001  (report whatever the API says)
        print(f"\nthread search failed: {exc}")
    try:
        root = bookcast.x_get(f"/tweets/{target['conversation_id']}", {"tweet.fields": "note_tweet,created_at"})
        print(f"thread root readable: {bool(root.get('data'))}, created {root.get('data', {}).get('created_at', '')[:10]}")
    except Exception as exc:  # noqa: BLE001
        print(f"thread root lookup failed: {exc}")


if __name__ == "__main__":
    {"auth": bookcast.x_auth, "test": test}[sys.argv[1]]()
