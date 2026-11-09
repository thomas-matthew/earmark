"""One daily run: find new saved items, decide which are worth an episode, write and voice them,
and publish the feed. Plain code drives the steps (L1); Claude only judges and writes."""
import asyncio
import fcntl
import json
import secrets
import time
import traceback
from dataclasses import dataclass, field

from . import sources
from .audio.voice import SAMPLE_RATE, Narrator
from .common import notify
from .common.web import LoginExpired
from .config import Settings
from .content import media
from .delivery import retention
from .delivery.feed import write_feed
from .llm import relevance, writer
from .llm.script import Line, Script
from .sources.base import Context
from .sources.x.api import CreditsDepleted, estimated_spend
from .storage import db as store
from .storage.db import Item

DAY = 86400
LOOKBACK_DAYS, LONG_LOOKBACK_DAYS, MIN_FIRST_ITEMS = 30, 60, 10  # D4
MAX_ATTEMPTS = 3
MAX_CONSECUTIVE_FAILURES = 3


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


@dataclass
class Report:
    found: int = 0
    skipped: int = 0
    published: int = 0
    failures: list[str] = field(default_factory=list)


# --- Finding new items -------------------------------------------------------------------------

def _lookback_days(db, first_run_items: list[Item], now: float) -> int:
    """Decided once, on the very first run: one month, or two if one month gives fewer than 10 items."""
    saved = store.meta_get(db, "lookback_days")
    if saved:
        return int(saved)
    recent = sum(i.item_date >= now - LOOKBACK_DAYS * DAY for i in first_run_items)
    days = LOOKBACK_DAYS if recent >= MIN_FIRST_ITEMS else LONG_LOOKBACK_DAYS
    store.meta_set(db, "lookback_days", str(days))
    log(f"first run: {recent} items in the last {LOOKBACK_DAYS} days, so looking back {days} days")
    return days


def sync(ctx: Context, settings: Settings, report: Report, only: set[str] | None = None) -> None:
    now = time.time()
    fetched: dict[str, tuple[bool, list[Item]]] = {}
    for module in sources.ALL:
        if only and module.NAME not in only:
            continue
        first_run = store.meta_get(ctx.db, f"synced:{module.NAME}") is None
        try:
            items = module.fetch(ctx, store.known_ids(ctx.db, module.NAME), first_run)
        except LoginExpired as exc:
            report.failures.append(str(exc))
            notify.send(settings, "Earmark: login expired", f"The {exc.source} login stopped working. Renew it in .env.", "high")
            continue
        except CreditsDepleted:
            report.failures.append("X credit used up")
            notify.send(settings, "Earmark: X credit used up", "Add X API credit to keep checking bookmarks.", "high")
            continue
        except Exception as exc:  # noqa: BLE001  one broken source must not stop the others
            report.failures.append(f"{module.LABEL} check failed: {exc}")
            log(f"{module.LABEL}: check failed: {exc}")
            continue
        fetched[module.NAME] = (first_run, items)

    first_items = [i for name, (first, items) in fetched.items() if first for i in items]
    lookback = _lookback_days(ctx.db, first_items, now) if first_items or store.meta_get(ctx.db, "lookback_days") else LOOKBACK_DAYS

    for name, (first_run, items) in fetched.items():
        module = sources.BY_NAME[name]
        added = baseline = 0
        for item in items:
            old = first_run and item.item_date < now - lookback * DAY
            if not old and hasattr(module, "enrich"):
                try:
                    module.enrich(ctx, item)
                except Exception as exc:  # noqa: BLE001  the item is still useful without its thread
                    log(f"{module.LABEL}: could not fetch the thread for {item.id}: {exc}")
            # Backfilled items keep their own date for ordering; later items are ordered by when they were found.
            inserted = store.insert(ctx.db, item, "baseline" if old else "new", sort_at=item.item_date if first_run else None)
            baseline += inserted and old
            added += inserted and not old
        store.meta_set(ctx.db, f"synced:{name}", str(now))
        report.found += added
        log(f"{module.LABEL}: {added} new" + (f", {baseline} older items recorded without processing" if first_run else ""))


def check_x_spending(ctx: Context, settings: Settings) -> None:
    spend = estimated_spend(ctx)
    key = "x_alerted:" + time.strftime("%Y-%m")
    if spend > settings.x_monthly_alert and not store.meta_get(ctx.db, key):
        notify.send(settings, "Earmark: X spending alert",
                    f"Estimated X API spend this month is ${spend:.2f}, over the ${settings.x_monthly_alert:.0f} alert.", "high")
        store.meta_set(ctx.db, key, "1")


# --- Making episodes ---------------------------------------------------------------------------

def _description(row, label: str, remaining: int) -> str:
    parts = [f"Saved on {label}.", f"Original: {row['url']}"]
    if row["link"] and row["link"] != row["url"]:
        parts.append(f"Link: {row['link']}")
    if remaining:
        parts.append(f"Review: {remaining} possible accuracy issue(s) remained after correction.")
    return "\n".join(parts)


def _media_link(row) -> str | None:
    payload = json.loads(row["payload"])
    if payload.get("podcast_url"):
        return payload["podcast_url"]
    return row["link"] if media.is_media_link(row["link"]) else None


def _publish(ctx: Context, settings: Settings, narrator: Narrator, row, script: Script, description: str,
             status: str, media_audio=None) -> None:
    name = f"{secrets.token_urlsafe(18)}.mp3"
    scripts = settings.data / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / f"{row['id'].replace(':', '_')}.txt").write_text(script.text(), encoding="utf-8")  # kept for checking episodes
    seconds = narrator.render(script, settings.feed_dir / name, media_audio, log=log)
    store.update(ctx.db, row["id"], status=status, episode_title=script.title or row["title"], description=description,
                 mp3=name, bytes=(settings.feed_dir / name).stat().st_size, seconds=seconds, published_at=time.time())
    write_feed(ctx.db, settings.feed_dir, settings.base_url)
    log(f"  published: {script.title or row['title']} ({seconds / 60:.1f} min)")


def process(ctx: Context, settings: Settings, narrator: Narrator, row, report: Report) -> None:
    module = sources.BY_NAME[row["source"]]
    log(f"{module.LABEL}: {row['title'][:80]} ({row['id']})")
    material = module.material(ctx, row)

    if module.FILTERED and row["decision"] is None:
        decision = asyncio.run(relevance.judge(row["title"], module.LABEL, material))
        store.update(ctx.db, row["id"], decision="include" if decision.include else "skip",
                     decision_reason=decision.reason, decision_confidence=decision.confidence)
        if not decision.include:
            store.update(ctx.db, row["id"], status="skipped")
            report.skipped += 1
            log(f"  skipped: {decision.reason}")
            return
        log(f"  included ({decision.confidence}): {decision.reason}")

    link = _media_link(row)
    info = None
    if link:
        try:
            info = media.describe(link)
        except Exception as exc:  # noqa: BLE001  fall back to an ordinary episode about the link
            log(f"  recording details unavailable: {exc}")
            link = None
    result = asyncio.run(writer.write(row, material, module.LABEL, info, log=log))
    media_audio = None
    if link:
        work = settings.work_dir / row["id"].replace(":", "_")
        try:
            media_audio = media.decode(media.download_audio(link, work), SAMPLE_RATE)
        finally:
            for leftover in work.glob("*"):
                leftover.unlink()
    _publish(ctx, settings, narrator, row, result.script, _description(row, module.LABEL, len(result.remaining)),
             "done", media_audio)
    if result.remaining:
        log("  remaining review issues: " + json.dumps(result.remaining, ensure_ascii=False)[:2000])
    report.published += 1


def give_up(ctx: Context, settings: Settings, narrator: Narrator, row, error: str) -> None:
    """After repeated failures, publish a short episode saying so (A6), so the item is not lost."""
    label = sources.BY_NAME[row["source"]].LABEL
    script = Script(f"Could not prepare: {row['title'][:60]}", [Line("N", (
        f"This is an item you saved on {label}, titled {row['title']}. Earmark tried {MAX_ATTEMPTS} times "
        f"but could not prepare it, so open it yourself from the episode notes."))])
    _publish(ctx, settings, narrator, row, script, _description(row, label, 0) + f"\nError: {error[:300]}", "failed")


def run(settings: Settings, limit: int | None = None, only_sources: set[str] | None = None,
        item_ids: list[str] | None = None, skip_sync: bool = False) -> Report:
    settings.data.mkdir(parents=True, exist_ok=True)
    lock = open(settings.data / "run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another Earmark run is in progress.")

    db = store.connect(settings.db_path)
    ctx, report = Context(settings, db), Report()
    log("run started")
    if not skip_sync:
        sync(ctx, settings, report, only_sources)
    check_x_spending(ctx, settings)

    rows = [r for r in ([store.get(db, i) for i in item_ids] if item_ids else store.pending(db)) if r is not None]
    if limit is not None:
        rows = rows[:limit]
    narrator, consecutive = Narrator(settings.voices_dir), 0
    for row in rows:
        try:
            process(ctx, settings, narrator, row, report)
            consecutive = 0
        except LoginExpired as exc:
            report.failures.append(str(exc))
            log(f"  {exc}; will retry next run")
        except Exception as exc:  # noqa: BLE001  keep going with the other items
            consecutive += 1
            attempts = row["attempts"] + 1
            store.update(db, row["id"], attempts=attempts, last_error=str(exc)[:1000])
            log(f"  failed (attempt {attempts}): {exc}\n{traceback.format_exc(limit=3)}")
            if attempts >= MAX_ATTEMPTS:
                try:
                    give_up(ctx, settings, narrator, row, str(exc))
                except Exception as final:  # noqa: BLE001
                    log(f"  could not publish the failure episode either: {final}")
            report.failures.append(f"{row['id']}: {exc}")
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                log("stopping: several items failed in a row, so something larger is wrong")
                break

    expired = retention.expire(db, settings.feed_dir, settings.retention_days)
    write_feed(db, settings.feed_dir, settings.base_url)
    log(f"run finished: {report.found} found, {report.skipped} skipped, {report.published} published, "
        f"{expired} expired, {len(report.failures)} problems")
    if report.failures:
        notify.send(settings, "Earmark: run had problems",
                    f"{len(report.failures)} problem(s) in today's run. See data/logs/run.log on the Mac.")
    return report
