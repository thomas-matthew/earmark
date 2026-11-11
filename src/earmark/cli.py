"""Command line for Earmark. Run `uv run earmark --help`."""
import argparse
import sys

from . import config


def cmd_run(settings, args) -> None:
    from . import pipeline

    only = set(args.source.split(",")) if args.source else None
    report = pipeline.run(settings, limit=args.limit, only_sources=only, item_ids=args.item, skip_sync=args.no_sync)
    sys.exit(1 if report.failures and not report.published else 0)


def cmd_serve(settings, args) -> None:
    from .delivery.server import serve

    serve(settings.feed_dir, settings.bind_host, settings.port)


def cmd_x_auth(settings, args) -> None:
    from .sources.x.auth import authorize

    authorize(settings)


def cmd_status(settings, args) -> None:
    from .sources.base import Context
    from .sources.x.api import estimated_spend, reads_this_month
    from .storage import db as store

    db = store.connect(settings.db_path)
    counts = dict(db.execute("SELECT status, COUNT(*) FROM items GROUP BY status").fetchall())
    print("Items: " + (", ".join(f"{s} {n}" for s, n in sorted(counts.items())) or "none yet"))
    print(f"X this month: {reads_this_month(Context(settings, db))} reads, about ${estimated_spend(Context(settings, db)):.2f}")
    print(f"Feed: {settings.base_url}/feed.xml")
    skipped = db.execute("SELECT id, title, decision_reason FROM items WHERE status='skipped' ORDER BY discovered_at DESC LIMIT ?",
                         (args.skipped,)).fetchall()
    if skipped:
        print("\nRecently skipped (use `earmark include ID` to override):")
        for row in skipped:
            print(f"  {row['id']:24} {row['title'][:60]:60} | {row['decision_reason']}")
    failing = db.execute("SELECT id, title, attempts, last_error FROM items WHERE status='new' AND attempts > 0").fetchall()
    if failing:
        print("\nRetrying:")
        for row in failing:
            print(f"  {row['id']:24} {row['title'][:50]:50} attempts {row['attempts']}: {(row['last_error'] or '')[:80]}")


def cmd_include(settings, args) -> None:
    from .storage import db as store

    db = store.connect(settings.db_path)
    for item_id in args.ids:
        row = store.get(db, item_id)
        if row is None:
            print(f"{item_id}: not found")
        elif row["status"] in ("skipped", "baseline"):
            store.update(db, item_id, status="new", decision="include", decision_reason="included by hand", attempts=0)
            print(f"{item_id}: queued for the next run")
        else:
            print(f"{item_id}: already {row['status']}")


def cmd_install(settings, args) -> None:
    from .service import launchd

    hour, minute = (int(part) for part in args.at.split(":"))
    for path in launchd.install(settings, hour, minute):
        print(f"Installed {path}")
    print(f"Feed server is running; the daily run starts at {args.at}. Logs: {settings.data / 'logs'}")


def cmd_uninstall(settings, args) -> None:
    from .service import launchd

    launchd.uninstall(settings)
    print("Removed the Earmark background service.")


def cmd_notify_test(settings, args) -> None:
    from .common import notify

    if not settings.ntfy_topic:
        sys.exit("Set NTFY_TOPIC in .env first.")
    print("Sent." if notify.send(settings, "Earmark", "Test alert from Earmark.") else "Sending failed.")


def cmd_doctor(settings, args) -> None:
    from .service import doctor

    sys.exit(0 if doctor.run(settings, args.x) else 1)


def cmd_claude_path(settings, args) -> None:
    from .llm.claude import CLI

    print(CLI)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="earmark", description="Turn saved items into a private podcast.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="check sources, make new episodes and publish the feed")
    run.add_argument("--limit", type=int, help="process at most this many items")
    run.add_argument("--source", help="only check these sources, comma separated: x,reddit,substack,hn")
    run.add_argument("--item", action="append", help="process this item id (repeatable)")
    run.add_argument("--no-sync", action="store_true", help="do not check sources, only process waiting items")
    run.set_defaults(handler=cmd_run)

    sub.add_parser("serve", help="serve the feed over HTTP").set_defaults(handler=cmd_serve)
    sub.add_parser("x-auth", help="approve read access to X bookmarks in a browser (once)").set_defaults(handler=cmd_x_auth)

    status = sub.add_parser("status", help="show item counts, X spending and skipped items")
    status.add_argument("--skipped", type=int, default=15, help="how many skipped items to list")
    status.set_defaults(handler=cmd_status)

    include = sub.add_parser("include", help="override a skip so the item gets an episode")
    include.add_argument("ids", nargs="+")
    include.set_defaults(handler=cmd_include)

    install = sub.add_parser("install", help="install the background service (LaunchAgents)")
    install.add_argument("--at", default="05:00", help="daily run time, HH:MM (default 05:00)")
    install.set_defaults(handler=cmd_install)
    sub.add_parser("uninstall", help="remove the background service").set_defaults(handler=cmd_uninstall)
    sub.add_parser("notify-test", help="send a test alert through ntfy").set_defaults(handler=cmd_notify_test)

    doctor = sub.add_parser("doctor", help="check logins, Claude and the voice model")
    doctor.add_argument("--x", action="store_true", help="also check the X login (one paid read)")
    doctor.set_defaults(handler=cmd_doctor)
    sub.add_parser("claude-path", help="print the Claude CLI bundled with the Agent SDK").set_defaults(handler=cmd_claude_path)

    args = parser.parse_args(argv)
    args.handler(config.load(), args)


if __name__ == "__main__":
    main()
