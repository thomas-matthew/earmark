"""Read web pages for the writer (C1, C8): main text through trafilatura, plus a list of the page's
images so the writer can look at charts. Only public internet addresses are fetched, including
after redirects, so a link in saved content can never reach this Mac or the home network."""
import html as html_lib
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import trafilatura

from ..common.web import BROWSER_AGENT, is_public

MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 25
MAX_REFRESH_PAGE = 4096  # only pages this small are treated as redirect notices
MAX_REFRESH_HOPS = 3
MIN_TEXT_CHARS = 500  # less text than this from a page with scripts tries the browser
SKIP_IMAGE = re.compile(r"logo|avatar|icon|sprite|favicon|badge|pixel|tracking|emoji|profile|\.svg($|\?)", re.I)


class _PublicOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public(newurl):
            raise urllib.error.URLError("redirect to a non-public address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_PublicOnlyRedirects)


def refresh_target(body: bytes, content_type: str, base: str) -> str | None:
    """The address a tiny redirect page sends the browser to. t.co answers non-browsers this way
    (a meta refresh or location.replace) instead of with an HTTP redirect."""
    if "html" not in content_type or len(body) > MAX_REFRESH_PAGE:
        return None
    markup = body.decode("utf-8", "replace")
    found = (re.search(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["'][^"']*?url=([^"'>]+)""", markup, re.I)
             or re.search(r"""location\.replace\(\s*["']([^"']+)["']""", markup))
    if not found:
        return None
    return urllib.parse.urljoin(base, html_lib.unescape(found.group(1).strip()).replace("\\/", "/"))


def fetch_bytes(url: str, accept: str = "*/*", limit: int = MAX_BYTES) -> tuple[bytes, str, str]:
    """Return (body, content type, final url), following HTTP redirects and tiny refresh pages.
    Raises ValueError for non-public or oversized responses."""
    for _ in range(MAX_REFRESH_HOPS + 1):
        if not is_public(url):
            raise ValueError("not a public address")
        request = urllib.request.Request(url, headers={"User-Agent": BROWSER_AGENT, "Accept": accept})
        with _opener.open(request, timeout=30) as resp:
            body = resp.read(limit + 1)
            if len(body) > limit:
                raise ValueError("response too large")
            content_type, final = resp.headers.get_content_type(), resp.geturl()
        target = refresh_target(body, content_type, final)
        if not target or target == final:
            return body, content_type, final
        url = target
    raise ValueError("too many refresh redirects")


@dataclass
class Page:
    url: str
    title: str | None
    text: str
    images: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, alt text)


def page_images(markup: str, base: str) -> list[tuple[str, str]]:
    found, seen = [], set()
    for tag in re.findall(r"<img\b[^>]*>", markup, re.I):
        src = re.search(r"""\bsrc=["']([^"']+)["']""", tag) or re.search(r"""\bdata-src=["']([^"']+)["']""", tag)
        if not src:
            continue
        url = urllib.parse.urljoin(base, html_lib.unescape(src.group(1)))
        alt_match = re.search(r"""\balt=["']([^"']*)["']""", tag)
        alt = html_lib.unescape(alt_match.group(1)).strip() if alt_match else ""
        if url in seen or url.startswith("data:") or SKIP_IMAGE.search(url):
            continue
        seen.add(url)
        found.append((url, alt))
    return found[:MAX_IMAGES]


def _extract(markup: str, url: str) -> Page | None:
    doc = trafilatura.bare_extraction(markup, url=url, with_metadata=True, include_tables=True, include_comments=False)
    if doc is None or not (doc.text or "").strip():
        return None
    return Page(url, doc.title, doc.text, page_images(markup, url))


def needs_browser(markup: str, page: Page | None) -> bool:
    """A page with scripts but next to no readable text is probably drawn by JavaScript."""
    return "<script" in markup.lower() and (page is None or len(page.text) < MIN_TEXT_CHARS)


def read_page(url: str, log=print) -> Page | None:
    """Main text of a page, or None if it cannot be read as an article."""
    try:
        body, content_type, final = fetch_bytes(url, "text/html,application/xhtml+xml")
    except (OSError, ValueError):
        return None
    if "html" not in content_type and "xml" not in content_type:
        return None
    markup = body.decode("utf-8", "replace")
    page = _extract(markup, final)
    if not needs_browser(markup, page):
        return page
    from . import browser
    try:
        rendered, rendered_url = browser.render(final)
    except Exception as exc:  # noqa: BLE001  the plain result is still better than nothing
        log(f"  browser could not render {final}: {type(exc).__name__}: {exc}")
        return page
    shown = _extract(rendered, rendered_url)
    log(f"  rendered {final} in a browser: {len(page.text) if page else 0} -> {len(shown.text) if shown else 0} characters")
    return shown if shown and (page is None or len(shown.text) > len(page.text)) else page
