"""`earmark doctor`: check every login and dependency once, without making episodes."""
import asyncio
import os
import urllib.parse
from pathlib import Path

from ..config import Settings
from ..sources.base import Context
from ..storage import db as store


def _check(name: str, func) -> bool:
    try:
        detail = func()
        print(f"  ok    {name}" + (f": {detail}" if detail else ""))
        return True
    except Exception as exc:  # noqa: BLE001  report everything, stop nothing
        print(f"  FAIL  {name}: {exc}")
        return False


def run(settings: Settings, include_x: bool) -> bool:
    ctx = Context(settings, store.connect(settings.db_path))
    print("Checking Earmark setup:")

    def claude():
        from ..llm import models
        from ..llm.claude import ask_once
        reply = asyncio.run(ask_once("Reply with exactly: OK", "Are you there?", model=models.DOCTOR))
        return f"replied in {reply.seconds:.0f}s"

    def reddit():
        from ..sources import reddit as source
        user = settings.secret("REDDIT_USERNAME")
        if not user:
            raise RuntimeError("REDDIT_USERNAME is not set")
        source._get(ctx, f"/user/{urllib.parse.quote(user)}/saved.json?limit=1")
        return None

    def substack():
        from ..sources import substack as source
        return f"{len(source._page(ctx, None).get('posts') or [])} saved posts on the first page"

    def hacker_news():
        if not settings.secret("HN_USERNAME"):
            raise RuntimeError("HN_USERNAME is not set")
        return None

    def x():
        from ..sources.x import api
        return "@" + api.get(ctx, "/users/me")["data"]["username"]

    def voice_model():
        cache = Path(os.environ["HF_HOME"]) / "hub" / "models--mlx-community--Breeze-TTS-2-mlx"
        if not cache.exists():
            raise RuntimeError(f"not downloaded yet; it downloads on the first run into {cache.parent}")
        return None

    def alerts():
        if not settings.ntfy_topic:
            raise RuntimeError("NTFY_TOPIC is not set")
        return None

    checks = [("Claude (subscription login)", claude), ("Reddit login", reddit), ("Substack login", substack),
              ("Hacker News username", hacker_news), ("Breeze voice model", voice_model), ("ntfy topic", alerts)]
    if include_x:
        checks.insert(1, ("X login (one paid read)", x))
    else:
        print("  skip  X login (pass --x to check it; it costs one paid read)")
    return all([_check(name, func) for name, func in checks])
