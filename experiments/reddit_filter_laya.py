"""Judge the 25 borderline Reddit items with Laya, a local decision model, and compare with Claude.

Usage (from experiments/): uv run python reddit_filter_laya.py
Threads are cached in data/reddit_docs/ so later runs make no Reddit requests.
"""
import json
import time
import urllib.parse

import bookcast  # noqa: F401  (points the model cache at the shared folder)
import laya

import llm_probe as probe
import reddit_filter_full as full
from reddit_probe import env, get

DOCS = probe.OUT / "reddit_docs"
QUESTION = {
    "decision": {
        "type": "choice",
        "instructions": "Should this saved Reddit item become a podcast episode for listening on a commute? "
                        "A post whose value is in its discussion should be included.",
        "criteria": {
            "include": "ideas, explanations, how something works, experiences and debates worth hearing through",
            "skip": "saved for reference: deals, shopping comparisons, local recommendations, itineraries, "
                    "link lists, prompt templates, or content that only makes sense on a screen",
        },
    }
}


def load_documents() -> dict[str, str]:
    DOCS.mkdir(exist_ok=True)
    docs, items, cookie = {}, None, None
    for index, (prefix, _) in enumerate(full.BORDERLINE):
        path = DOCS / f"{index:02d}.txt"
        if not path.exists():
            if items is None:
                cookie, user = env("REDDIT_SESSION"), urllib.parse.quote(env("REDDIT_USERNAME"))
                items = json.loads(get(f"/user/{user}/saved.json?limit=100&raw_json=1", cookie)[1])["data"]["children"]
            match = next((i for i in items if (i["data"].get("title") or i["data"].get("link_title") or "").startswith(prefix)), None)
            if match is None:
                continue
            time.sleep(2)
            path.write_text(full.document(match, cookie)[0])
        docs[prefix] = path.read_text()
    return docs


def main() -> None:
    docs = load_documents()
    start = time.time()
    agent = laya.Agent(vegaml=True)
    print(f"model loaded in {time.time() - start:.0f}s", flush=True)

    claude = {}
    for model in ("full", "sonnet", "haiku", "opus"):
        path = probe.OUT / f"reddit_filter_{model}.json"
        if path.exists():
            for row in json.loads(path.read_text()):
                claude.setdefault(row["title"], {})["opus1" if model == "full" else model] = row.get("decision", row.get(model))

    results = []
    for prefix, text in docs.items():
        begin = time.time()
        out = agent.predict(text, QUESTION)
        seconds = time.time() - begin
        answer = out["answers"]["decision"]
        usage = out.get("usage", {})
        probs = answer.get("probabilities", {})
        unsure = bool(answer.get("abstain")) or len(answer.get("prediction_set") or []) > 1
        final = "include" if unsure else answer.get("choice")
        row = {"title": prefix, "laya": answer.get("choice"), "final": final, "p_include": round(probs.get("include", 0), 2),
               "unsure": unsure, "truncated": usage.get("truncated"), "tokens": usage.get("state_tokens"),
               "dropped": usage.get("state_tokens_dropped"), "seconds": round(seconds, 2), **claude.get(prefix, {})}
        results.append(row)
        print(f"{row['laya']:7} p={row['p_include']:.2f} unsure={str(unsure):5} final={final:7} "
              f"tokens={row['tokens']} truncated={row['truncated']} {seconds:5.2f}s  {prefix[:40]:40} "
              f"claude={claude.get(prefix, {})}", flush=True)

    (probe.OUT / "reddit_filter_laya.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"\n{len(results)} judged, avg {sum(r['seconds'] for r in results) / len(results):.2f}s per item, "
          f"{sum(bool(r['truncated']) for r in results)} truncated, {sum(r['unsure'] for r in results)} unsure")
    for model in ("opus1", "sonnet", "haiku", "opus"):
        pairs = [(r["final"], r[model]) for r in results if model in r]
        if pairs:
            print(f"agreement with {model}: {sum(a == b for a, b in pairs)}/{len(pairs)}")


if __name__ == "__main__":
    main()
