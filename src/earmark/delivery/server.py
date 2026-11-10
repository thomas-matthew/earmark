"""A small web server for the feed and episode files over Tailscale (A3).
Supports Range requests so the phone can resume a partial download."""
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .feed import FEED_NAME

SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+\.(mp3|xml|png)$")
CONTENT_TYPES = {"mp3": "audio/mpeg", "xml": "application/rss+xml; charset=utf-8", "png": "image/png"}


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return the inclusive byte range asked for, or None for the whole file. Raises ValueError if unsatisfiable."""
    if not header:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or match.groups() == ("", ""):
        return None  # unsupported forms (such as multiple ranges) get the whole file, which is allowed
    start_text, end_text = match.groups()
    if start_text:
        start = int(start_text)
        end = min(int(end_text), size - 1) if end_text else size - 1
    else:
        start, end = max(size - int(end_text), 0), size - 1
    if start >= size or start > end:
        raise ValueError("unsatisfiable range")
    return start, end


def make_handler(feed_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Earmark"
        sys_version = ""

        def do_HEAD(self):
            self._serve(send_body=False)

        def do_GET(self):
            self._serve(send_body=True)

        def _serve(self, send_body: bool):
            name = self.path.split("?", 1)[0].lstrip("/") or FEED_NAME
            path = feed_dir / name
            if not SAFE_NAME.match(name) or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            size = path.stat().st_size
            try:
                wanted = parse_range(self.headers.get("Range"), size)
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            start, end = wanted or (0, size - 1)
            self.send_response(HTTPStatus.PARTIAL_CONTENT if wanted else HTTPStatus.OK)
            self.send_header("Content-Type", CONTENT_TYPES[name.rsplit(".", 1)[1]])
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if wanted:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if send_body:
                self._send_bytes(path, start, end - start + 1)

        def _send_bytes(self, path: Path, start: int, remaining: int):
            with path.open("rb") as f:
                f.seek(start)
                while remaining > 0:
                    chunk = f.read(min(1 << 16, remaining))
                    if not chunk:
                        return
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return  # the phone stopped downloading; it will resume with a Range request
                    remaining -= len(chunk)

        def log_message(self, fmt, *args):
            pass  # no per-request logs; nothing useful and it grows forever

    return Handler


def serve(feed_dir: Path, host: str, port: int) -> None:
    feed_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), make_handler(feed_dir))
    print(f"Serving {feed_dir} on http://{host}:{port}/{FEED_NAME}", flush=True)
    server.serve_forever()
