"""A headless browser for pages that only show their text after running JavaScript (C1).

Used only as a fallback when the plain fetch finds next to no text. It drives the Mac's own Google
Chrome through Playwright, headless, with a fresh temporary profile each time, so it never sees the
person's Chrome profile, cookies or logins. Every request the page makes is checked: only public
internet addresses load, so a page's scripts cannot reach this Mac or the home network.
Images, media and fonts are skipped, downloads are refused and service workers are blocked."""
import concurrent.futures
import urllib.parse

from ..common.web import BROWSER_AGENT, is_public

CHANNEL = "chrome"  # the installed Google Chrome; no separate browser download
LOAD_TIMEOUT_MS = 30_000
SETTLE_SECONDS = 15  # time for the page's scripts (and any "checking your browser" wait page) to finish
SETTLED_CHARS = 500  # the page counts as drawn once it has this much text and stops changing
SKIPPED_RESOURCES = {"image", "media", "font"}


class BrowserUnavailable(Exception):
    pass


def _settle(page, error) -> None:
    """Wait until the page's text has grown and stopped changing, like a reader waiting for it to load.
    Some sites show a short wait page first; it is given time to finish on its own, never worked around."""
    previous = -1
    for _ in range(SETTLE_SECONDS):
        page.wait_for_timeout(1000)
        try:
            size = len(page.inner_text("body"))
        except error:
            continue  # the page is navigating; look again next second
        if size >= SETTLED_CHARS and size == previous:
            return
        previous = size


def _render(url: str) -> tuple[str, str]:
    from playwright.sync_api import Error, sync_playwright

    allowed: dict[str, bool] = {}

    def check(route):
        request = route.request
        host = urllib.parse.urlparse(request.url).hostname or ""
        if request.resource_type in SKIPPED_RESOURCES:
            return route.abort()
        if request.url.startswith(("data:", "blob:")):
            return route.continue_()
        if host not in allowed:
            allowed[host] = is_public(request.url)
        return route.continue_() if allowed[host] else route.abort()

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel=CHANNEL, headless=True)
        except Error as exc:
            raise BrowserUnavailable(str(exc).splitlines()[0]) from exc
        try:
            context = browser.new_context(user_agent=BROWSER_AGENT, accept_downloads=False, service_workers="block",
                                          java_script_enabled=True)
            context.route("**/*", check)
            page = context.new_page()
            page.goto(url, timeout=LOAD_TIMEOUT_MS, wait_until="domcontentloaded")
            _settle(page, Error)
            return page.content(), page.url
        finally:
            browser.close()


def render(url: str) -> tuple[str, str]:
    """Return (rendered HTML, final url). Runs in its own thread, because Playwright's synchronous
    API refuses to run inside the writer's asyncio event loop."""
    if not is_public(url):
        raise ValueError("not a public address")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        markup, final = pool.submit(_render, url).result(timeout=LOAD_TIMEOUT_MS / 1000 + SETTLE_SECONDS + 30)
    if not is_public(final):
        raise ValueError("ended on a non-public address")
    return markup, final
