"""Small HTTP helpers shared by the sources, with retries for temporary failures."""
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

BROWSER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
RETRY_STATUSES = {429, 500, 502, 503, 504}


class LoginExpired(Exception):
    """A source rejected the stored login. The message names only the source, never the secret."""

    def __init__(self, source: str):
        super().__init__(f"{source} login is no longer accepted")
        self.source = source


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        host = urllib.parse.urlparse(url).hostname
        super().__init__(f"HTTP {status} from {host}")
        self.status = status
        self.body = body


def request(url: str, headers: dict | None = None, data: bytes | None = None, timeout: int = 30,
            attempts: int = 3) -> tuple[int, bytes, dict]:
    """Return (status, body, headers). Retries network errors and 429/5xx with backoff."""
    headers = {"User-Agent": BROWSER_AGENT, **(headers or {})}
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code not in RETRY_STATUSES or attempt == attempts - 1:
                return exc.code, body, dict(exc.headers or {})
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(2 * 3 ** attempt)
    raise AssertionError("unreachable")


def get_json(url: str, headers: dict | None = None, data: bytes | None = None) -> dict | list:
    status, body, _ = request(url, {"Accept": "application/json", **(headers or {})}, data)
    if status != 200:
        raise HttpError(status, url, body.decode("utf-8", "replace")[:300])
    return json.loads(body)


def get_text(url: str, headers: dict | None = None) -> str:
    status, body, _ = request(url, headers)
    if status != 200:
        raise HttpError(status, url)
    return body.decode("utf-8", "replace")


def is_public(url: str) -> bool:
    """Only fetch public internet addresses, so tool calls can't reach this Mac or the local network."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)
