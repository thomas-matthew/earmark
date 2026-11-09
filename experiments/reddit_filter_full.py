"""Re-judge borderline saved Reddit items one at a time, with the full post and every comment.

Usage (from experiments/): uv run python reddit_filter_full.py
"""
import json
import time
import urllib.parse
from pathlib import Path

import llm_probe as probe
from reddit_filter_probe import SYSTEM as BATCH_SYSTEM
from reddit_probe import env, get

SYSTEM = BATCH_SYSTEM.replace(
    "Reply with only a JSON array containing one object per item, in the same order, with keys",
    "You receive one item with its full post and complete comment thread. A post whose value is in its\n"
    "discussion should be included. Reply with only a JSON object with keys",
)

# Items an earlier trimmed, batched run marked as low confidence, as [title start, earlier decision].
# These are my own saved posts, so they live in a git-ignored file rather than in the code.
BORDERLINE_FILE = Path(__file__).resolve().parent / "data" / "reddit_borderline.json"
BORDERLINE = [tuple(item) for item in json.loads(BORDERLINE_FILE.read_text())] if BORDERLINE_FILE.exists() else []


def flatten(children: list, depth: int = 0) -> list[str]:
    lines = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        d = child["data"]
        lines.append(f"{'  ' * depth}[{d['name']} score {d.get('score')}] {d.get('body', '')}")
        replies = d.get("replies")
        if replies:
            lines += flatten(replies["data"]["children"], depth + 1)
    return lines


def document(item: dict, cookie: str) -> tuple[str, int]:
    d = item["data"]
    permalink = d["permalink"] if item["kind"] == "t3" else urllib.parse.urlparse(d["link_permalink"]).path
    status, body = get(f"{permalink.rstrip('/')}.json?limit=500&raw_json=1", cookie)
    if status != 200:
        raise RuntimeError(f"thread fetch failed: {status}")
    post_listing, comment_listing = json.loads(body)
    post = post_listing["data"]["children"][0]["data"]
    focus = f"\nSAVED COMMENT (the item being judged):\n{d.get('body')}\n" if item["kind"] == "t1" else ""
    text = (f"Item id: {d['name']}\nType: {'comment' if item['kind'] == 't1' else 'post'}\n"
            f"Subreddit: r/{post.get('subreddit')}\nTitle: {post.get('title')}\n"
            f"Link: {None if post.get('is_self') else post.get('url')}\n{focus}\n"
            f"<post>\n{post.get('selftext', '')}\n</post>\n\n<comments>\n" + "\n".join(flatten(comment_listing["data"]["children"])) + "\n</comments>")
    return text, len(text)


def main() -> None:
    cookie, user = env("REDDIT_SESSION"), urllib.parse.quote(env("REDDIT_USERNAME"))
    status, body = get(f"/user/{user}/saved.json?limit=100&raw_json=1", cookie)
    items = json.loads(body)["data"]["children"]
    probe.SYSTEM = SYSTEM
    results = []
    for prefix, before in BORDERLINE:
        match = next((i for i in items if (i["data"].get("title") or i["data"].get("link_title") or "").startswith(prefix)), None)
        if match is None:
            print(f"not found: {prefix}")
            continue
        time.sleep(2)  # keep Reddit requests slow and polite
        text, size = document(match, cookie)
        raw = probe.call_claude(text)["result"]
        decision = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        changed = "CHANGED" if decision["decision"] != before else "same"
        results.append({"title": prefix, "chars": size, "before": before, **decision})
        print(f"{changed:7} {before:7} -> {decision['decision']:7} ({decision.get('confidence')}) "
              f"{size:7} chars  {prefix[:45]:45} | {decision.get('reason')}", flush=True)
    (probe.OUT / "reddit_filter_full.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    changed = sum(r["decision"] != r["before"] for r in results)
    print(f"\n{len(results)} judged, {changed} changed, {sum(r['confidence'] == 'low' for r in results)} still low confidence")


if __name__ == "__main__":
    main()
