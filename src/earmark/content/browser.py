"""A headless browser for pages that only show their text after running JavaScript (C1).

Used only as a fallback when the plain fetch finds next to no text. It drives the Mac's own Google
Chrome through Playwright, headless. Nothing from the person's own Chrome may reach it, and every
launch checks that before any page loads:

- The profile is an empty folder Earmark creates in the temp directory and deletes afterwards; it
  must not be inside Chrome's own profile folder, and Chrome must report using it.
- The privacy flags (no extensions, no sync, no keychain, no background calls to Google) are set
  here rather than trusted to Playwright's defaults, and Chrome must report all of them.
- Chrome's own sandbox for page processes stays on (Playwright turns it off by default).
- No Chrome policy may apply: none in the macOS managed preferences, no cloud enrollment token,
  and Chrome's policy page must show none set. Policies can apply even with a fresh profile.
- The browser must start with no cookies.

If any check fails the page is not opened, and the reader falls back to the plain fetch.
Every request a page makes is checked too: only public internet addresses load, so a page's
scripts cannot reach this Mac or the home network. Images, media and fonts are skipped,
downloads are refused and service workers are blocked."""
import concurrent.futures
import contextlib
import getpass
import os
import tempfile
import urllib.parse
from pathlib import Path

from ..common.web import BROWSER_AGENT, is_public

CHANNEL = "chrome"  # the installed Google Chrome; no separate browser download
LOAD_TIMEOUT_MS = 30_000
SETTLE_SECONDS = 15  # time for the page's scripts (and any "checking your browser" wait page) to finish
SETTLED_CHARS = 500  # the page counts as drawn once it has this much text and stops changing
SKIPPED_RESOURCES = {"image", "media", "font"}

CHROME_DATA = Path.home() / "Library/Application Support/Google"  # the person's Chrome profiles live here
PRIVACY_FLAGS = (
    "--disable-extensions", "--disable-sync", "--use-mock-keychain", "--password-store=basic",
    "--disable-background-networking", "--disable-component-update", "--disable-breakpad",
    "--disable-default-apps", "--no-first-run", "--metrics-recording-only",
)
FORBIDDEN_FLAGS = ("--no-sandbox",)
POLICY_FILES = (
    Path("/Library/Managed Preferences/com.google.Chrome.plist"),
    Path("/Library/Managed Preferences") / getpass.getuser() / "com.google.Chrome.plist",
    Path("/Library/Google/Chrome/CloudManagementEnrollmentToken"),
)
BROWSER_POLICY_LISTS = ("Chrome Policies", "Extension Install Policies")


class BrowserUnavailable(Exception):
    pass


class UnsafeBrowser(Exception):
    """A launch check failed, so no page was opened."""


def _inside(path: str | Path, folder: str | Path) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def check_profile_folder(folder: str) -> None:
    if _inside(folder, CHROME_DATA) or not _inside(folder, tempfile.gettempdir()):
        raise UnsafeBrowser(f"profile folder {folder} is not a private temporary folder")


def check_no_policy_files(paths=POLICY_FILES) -> None:
    found = [str(p) for p in paths if p.exists()]
    if found:
        raise UnsafeBrowser(f"Chrome policies are configured on this Mac: {', '.join(found)}")


def check_version_page(text: str, folder: str) -> None:
    """Check chrome://version: the profile Chrome is using, and the flags it was started with."""
    fields = dict(line.split("\t", 1) for line in text.splitlines() if "\t" in line)
    command_line, profile = fields.get("Command Line", ""), fields.get("Profile Path", "")
    if not profile or not _inside(profile, folder):
        raise UnsafeBrowser(f"Chrome is using profile {profile or 'unknown'}, not {folder}")
    flags = set(command_line.split())
    missing = [f for f in PRIVACY_FLAGS if f not in flags]
    present = [f for f in FORBIDDEN_FLAGS if f in flags]
    if missing or present:
        raise UnsafeBrowser(f"Chrome flags: missing {missing}, unwanted {present}")


def _check_policy_page(page) -> None:
    """chrome://policy must list no browser policies. Its "Google Update Policies" list is left out:
    it shows the updater's own built-in defaults, which only govern updates."""
    page.goto("chrome://policy")
    page.locator("text=No policies set").first.wait_for(timeout=5000)
    for title in BROWSER_POLICY_LISTS:
        listing = page.locator("policy-table").filter(has_text=title)
        if listing.count() != 1:
            raise UnsafeBrowser(f"could not find Chrome's {title!r} list")  # fail closed if the page changes
        shown = listing.locator("policy-row:visible").count()
        if shown:
            raise UnsafeBrowser(f"Chrome reports {shown} {title} set")


@contextlib.contextmanager
def session():
    """A checked, empty headless Chrome. Yields (context, page, profile folder); the browser closes
    and the folder is deleted on exit."""
    from playwright.sync_api import Error, sync_playwright

    check_no_policy_files()
    with tempfile.TemporaryDirectory(prefix="earmark-browser-", ignore_cleanup_errors=True) as folder, \
            sync_playwright() as p:
        check_profile_folder(folder)
        try:
            context = p.chromium.launch_persistent_context(
                folder, channel=CHANNEL, headless=True, chromium_sandbox=True, args=list(PRIVACY_FLAGS),
                user_agent=BROWSER_AGENT, accept_downloads=False, service_workers="block")
        except Error as exc:
            raise BrowserUnavailable(str(exc).splitlines()[0]) from exc
        try:
            context.route("**/*", _public_only())
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("chrome://version")
            check_version_page(page.inner_text("body"), folder)
            _check_policy_page(page)
            if context.cookies():
                raise UnsafeBrowser("the browser started with cookies")
            yield context, page, folder
        finally:
            context.close()


def _public_only():
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

    return check


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
    from playwright.sync_api import Error

    with session() as (_context, page, _folder):
        page.goto(url, timeout=LOAD_TIMEOUT_MS, wait_until="domcontentloaded")
        _settle(page, Error)
        return page.content(), page.url


def render(url: str) -> tuple[str, str]:
    """Return (rendered HTML, final url). Runs in its own thread, because Playwright's synchronous
    API refuses to run inside the writer's asyncio event loop."""
    if not is_public(url):
        raise ValueError("not a public address")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        markup, final = pool.submit(_render, url).result(timeout=LOAD_TIMEOUT_MS / 1000 + SETTLE_SECONDS + 45)
    if not is_public(final):
        raise ValueError("ended on a non-public address")
    return markup, final
