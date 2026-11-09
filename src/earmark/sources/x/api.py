"""Calls to the X API, with a meter for pay-per-use spending (T4).

X bills per resource read. The meter counts posts and users returned each month and multiplies by
the configured rate, so it is an estimate; X's developer console has the exact figure."""
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


def month_key(now: float | None = None) -> str:
    return "x_reads:" + time.strftime("%Y-%m", time.localtime(now or time.time()))


def reads_this_month(ctx: Context) -> int:
    return int(store.meta_get(ctx.db, month_key(), "0"))


def estimated_spend(ctx: Context) -> float:
    return reads_this_month(ctx) * ctx.settings.x_cost_per_read


def _count(body: dict) -> int:
    data = body.get("data")
    count = len(data) if isinstance(data, list) else int(bool(data))
    includes = body.get("includes") or {}
    return count + len(includes.get("tweets") or []) + len(includes.get("users") or [])


def get(ctx: Context, path: str, params: dict | None = None) -> dict:
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
    store.meta_set(ctx.db, key, str(int(store.meta_get(ctx.db, key, "0")) + _count(result)))
    return result
