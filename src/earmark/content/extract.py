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
SKIP_IMAGE = re.compile(r"logo|avatar|icon|sprite|favicon|badge|pixel|tracking|emoji|profile|\.svg($|\?)", re.I)


class _PublicOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public(newurl):
            raise urllib.error.URLError("redirect to a non-public address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_PublicOnlyRedirects)


def fetch_bytes(url: str, accept: str = "*/*", limit: int = MAX_BYTES) -> tuple[bytes, str, str]:
    """Return (body, content type, final url). Raises ValueError for non-public or oversized responses."""
    if not is_public(url):
        raise ValueError("not a public address")
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_AGENT, "Accept": accept})
    with _opener.open(request, timeout=30) as resp:
        body = resp.read(limit + 1)
        if len(body) > limit:
            raise ValueError("response too large")
        return body, resp.headers.get_content_type(), resp.geturl()


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


def read_page(url: str) -> Page | None:
    """Main text of a page, or None if it cannot be read as an article."""
    try:
        body, content_type, final = fetch_bytes(url, "text/html,application/xhtml+xml")
    except (OSError, ValueError):
        return None
    if "html" not in content_type and "xml" not in content_type:
        return None
    markup = body.decode("utf-8", "replace")
    doc = trafilatura.bare_extraction(markup, url=final, with_metadata=True, include_tables=True, include_comments=False)
    if doc is None or not (doc.text or "").strip():
        return None
    return Page(final, doc.title, doc.text, page_images(markup, final))
