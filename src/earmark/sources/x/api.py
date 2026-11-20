"""Calls to the X API, with a meter for pay-per-use spending (T4).

X bills per resource returned: $0.005 a post, $0.010 a user, and $0.001 for "owned reads" of my own
data such as my bookmarks. Objects pulled in through expansions (the includes section) were free
until 2026-11-22 and are billed at the same rates from then on. The meter prices each response that
way and adds it up per month. It is still an estimate: X also skips repeat reads of the same object
within a UTC day, which the meter ignores, so it errs high. X's developer console has the exact figure."""
from datetime import datetime, timezone
import json
import time
import urllib.parse

from ...common import web
from ...common.web import LoginExpired
from ...storage import db as store
from ..base import Context
from .auth import API, access_token


class CreditsDepleted(Exception):
    """X refused the request because the prepaid credit has run out."""


POST, USER, OWNED = 0.005, 0.010, 0.001
INCLUDE_RATES = {"tweets": POST, "users": USER, "media": 0.005, "polls": 0.005, "places": 0.005}
EXPANSIONS_BILLED_FROM = datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp()


def month_key(now: float | None = None) -> str:
    return "x_spend:" + time.strftime("%Y-%m", time.localtime(now or time.time()))


def estimated_spend(ctx: Context) -> float:
    return float(store.meta_get(ctx.db, month_key(), "0"))


def cost(path: str, body: dict, owned: bool = False, now: float | None = None) -> float:
    """What X charges for one response, in dollars."""
    data = body.get("data")
    count = len(data) if isinstance(data, list) else int(bool(data))
    rate = OWNED if owned else USER if path.startswith("/users") and not path.endswith("/bookmarks") else POST
    total = count * rate
    if (now or time.time()) >= EXPANSIONS_BILLED_FROM:
        includes = body.get("includes") or {}
        total += sum(len(includes.get(kind) or []) * price for kind, price in INCLUDE_RATES.items())
    return total


def get(ctx: Context, path: str, params: dict | None = None, owned: bool = False) -> dict:
    """A read-only GET. owned marks reads of my own data (my bookmarks), which X bills at the owned rate."""
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    status, body, _ = web.request(url, {"Authorization": f"Bearer {access_token(ctx.settings)}", "Accept": "application/json"})
    if status == 401:
        raise LoginExpired("X")
    if status == 402:
        raise CreditsDepleted("X API credit is used up")
    if status != 200:
        raise web.HttpError(status, url, body.decode("utf-8", "replace")[:300])
    result = json.loads(body)
    key = month_key()
    store.meta_set(ctx.db, key, f"{estimated_spend(ctx) + cost(path, result, owned):.4f}")
    return result
