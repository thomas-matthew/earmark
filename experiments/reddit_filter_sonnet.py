"""Rerun the full-thread borderline Reddit decisions on Sonnet and compare them with Opus.

Usage (from experiments/): uv run python reddit_filter_sonnet.py
"""
import json
import sys
import time
import urllib.parse

import llm_probe as probe
import reddit_filter_full as full
from reddit_probe import env, get


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "sonnet"
    opus = {r["title"]: r for r in json.loads((probe.OUT / "reddit_filter_full.json").read_text())}
    cookie, user = env("REDDIT_SESSION"), urllib.parse.quote(env("REDDIT_USERNAME"))
    items = json.loads(get(f"/user/{user}/saved.json?limit=100&raw_json=1", cookie)[1])["data"]["children"]
    probe.SYSTEM = full.SYSTEM
    results, agree = [], 0
    for prefix, _ in full.BORDERLINE:
        match = next((i for i in items if (i["data"].get("title") or i["data"].get("link_title") or "").startswith(prefix)), None)
        if match is None or prefix not in opus:
            print(f"skipped: {prefix}")
            continue
        time.sleep(2)
        text, _ = full.document(match, cookie)
        result = probe.call_claude(text, model=model)
        raw = result["result"]
        decision = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        same = decision["decision"] == opus[prefix]["decision"]
        agree += same
        results.append({"title": prefix, "opus": opus[prefix]["decision"], model: decision["decision"],
                        "confidence": decision.get("confidence"), "reason": decision.get("reason"),
                        "model": list(result.get("modelUsage", {})), "seconds": result.get("duration_ms", 0) / 1000})
        print(f"{'same' if same else 'DIFFERS':7} opus {opus[prefix]['decision']:7} {model} {decision['decision']:7} "
              f"({decision.get('confidence')}) {result.get('duration_ms', 0) / 1000:4.0f}s  {prefix[:42]:42} | {decision.get('reason')}", flush=True)
    (probe.OUT / f"reddit_filter_{model}.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    models = {m for r in results for m in r["model"]}
    print(f"\n{len(results)} judged, {agree} agree with Opus, models used: {sorted(models)}, "
          f"avg {sum(r['seconds'] for r in results) / max(len(results), 1):.0f}s per item")


if __name__ == "__main__":
    main()
