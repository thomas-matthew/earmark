"""Turn bookmarks into a private podcast, one full-length episode per bookmark.

Commands:
  add URL      queue a link by hand
  x-auth       authorize access to your X bookmarks (once)
  run          fetch new X bookmarks if configured, render pending items, rebuild the feed
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from xml.sax.saxutils import escape

os.environ.setdefault("HF_HOME", str(Path.home() / "Dev" / "labs" / "huggingface"))  # models are shared across projects
DATA = Path(os.environ.get("BOOKCAST_DATA", Path(__file__).parent / "data"))
FEED_DIR = DATA / "feed"
DB_PATH = DATA / "bookcast.db"
TOKEN_PATH = DATA / "x_token.json"

BASE_URL = os.environ.get("BOOKCAST_BASE_URL", "http://localhost:8765").rstrip("/")
VOICE = os.environ.get("BOOKCAST_VOICE", "af_heart")
TTS_MODEL = "mlx-community/Kokoro-82M-bf16"
SAMPLE_RATE = 24000
MIN_ARTICLE_CHARS = 200

X_API = "https://api.x.com/2"
X_REDIRECT = "http://127.0.0.1:8723/callback"
X_SCOPES = "tweet.read users.read bookmark.read offline.access"


# --- Storage ---------------------------------------------------------------

def connect() -> sqlite3.Connection:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            post_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,          -- pending | done | baseline
            title TEXT,
            note TEXT,                     -- why an item could not be read in full
            mp3 TEXT,
            bytes INTEGER,
            seconds REAL,
            added_at REAL NOT NULL,
            published_at REAL
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    return db


def add_item(db, item_id: str, source: str, url: str, post_text: str = "", status: str = "pending") -> bool:
    """Record an item; returns True only if it was not seen before."""
    cur = db.execute(
        "INSERT OR IGNORE INTO items (id, source, url, post_text, status, added_at) VALUES (?,?,?,?,?,?)",
        (item_id, source, url, post_text, status, time.time()),
    )
    db.commit()
    return cur.rowcount == 1


# --- X bookmarks -----------------------------------------------------------

def http_json(url: str, headers: dict, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def token_request(fields: dict) -> dict:
    client_id = os.environ["X_CLIENT_ID"]
    secret = os.environ.get("X_CLIENT_SECRET")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if secret:
        pair = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        headers["Authorization"] = f"Basic {pair}"
    else:
        fields = {**fields, "client_id": client_id}
    token = http_json(f"{X_API}/oauth2/token", headers, urllib.parse.urlencode(fields).encode())
    token["expires_at"] = time.time() + token.get("expires_in", 0)
    return token


def save_token(token: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(token, f)


def x_auth() -> None:
    if "X_CLIENT_ID" not in os.environ:
        sys.exit("Set X_CLIENT_ID first (see README).")
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(16)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": os.environ["X_CLIENT_ID"], "redirect_uri": X_REDIRECT,
        "scope": X_SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })
    result: dict = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            result.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab.")

        def log_message(self, *args):
            pass

    url = f"https://x.com/i/oauth2/authorize?{query}"
    print(f"Opening X to authorize. If nothing opens, visit:\n{url}")
    webbrowser.open(url)
    HTTPServer(("127.0.0.1", 8723), Callback).handle_request()
    if result.get("state", [None])[0] != state or "code" not in result:
        sys.exit("Authorization failed or was declined.")
    save_token(token_request({
        "grant_type": "authorization_code", "code": result["code"][0],
        "redirect_uri": X_REDIRECT, "code_verifier": verifier,
    }))
    print("Authorized.")


def x_access_token() -> str:
    token = json.loads(TOKEN_PATH.read_text())
    if time.time() > token["expires_at"] - 60:
        token = token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
        save_token(token)
    return token["access_token"]


def x_get(path: str, params: dict | None = None) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return http_json(f"{X_API}{path}{query}", {"Authorization": f"Bearer {x_access_token()}"})


def parse_tweet(tweet: dict, users: dict) -> tuple[str, str, str]:
    """Return (item id, url to read, post text) for one bookmarked post."""
    note = tweet.get("note_tweet") or {}
    text = note.get("text") or tweet.get("text", "")
    entities = note.get("entities") or tweet.get("entities") or {}
    author = users.get(tweet.get("author_id"), "i")
    own_url = f"https://x.com/{author}/status/{tweet['id']}"
    for link in entities.get("urls", []):
        expanded = link.get("expanded_url") or link.get("url") or ""
        host = urllib.parse.urlparse(expanded).hostname or ""
        if expanded and host not in {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "t.co"}:
            return f"x:{tweet['id']}", expanded, text
    return f"x:{tweet['id']}", own_url, text


def x_bookmark_pages(user_id: str, page_size: int, max_pages: int):
    params = {
        "max_results": page_size, "expansions": "author_id", "user.fields": "username",
        "tweet.fields": "note_tweet,entities",
    }
    for _ in range(max_pages):
        page = x_get(f"/users/{user_id}/bookmarks", params)
        users = {u["id"]: u["username"] for u in page.get("includes", {}).get("users", [])}
        yield [parse_tweet(t, users) for t in page.get("data", [])]
        next_token = page.get("meta", {}).get("next_token")
        if not next_token:
            return
        params = {**params, "pagination_token": next_token}


def sync_x(db) -> None:
    """Queue unseen bookmarks. The first run records all existing ones without queueing them,
    so a later un-bookmark can't push an old post back into the 'recent' window as if new."""
    if not TOKEN_PATH.exists():
        print("X: not authorized yet, skipping.")
        return
    baselined = db.execute("SELECT 1 FROM meta WHERE key='x_baseline'").fetchone()
    user_id = x_get("/users/me")["data"]["id"]
    page_size, max_pages = (20, 1) if baselined else (100, 10)
    status = "pending" if baselined else "baseline"
    fresh = 0
    for page in x_bookmark_pages(user_id, page_size, max_pages):
        fresh += sum(add_item(db, i, "X", url, text, status) for i, url, text in page)
    if not baselined:
        db.execute("INSERT INTO meta VALUES ('x_baseline', ?)", (str(time.time()),))
        db.commit()
    print(f"X: {fresh} {'queued' if baselined else 'existing bookmarks recorded, none queued'}.")


# --- Content ---------------------------------------------------------------

def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def extract(url: str) -> tuple[str | None, str | None]:
    """Return (title, full text); text is None when the page yields no real article."""
    import trafilatura

    if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
        return None, None
    html = trafilatura.fetch_url(url)
    if not html:
        return None, None
    doc = trafilatura.bare_extraction(html, url=url, with_metadata=True, include_comments=False, include_tables=False)
    if doc is None or len(doc.text or "") < MIN_ARTICLE_CHARS:
        return getattr(doc, "title", None), None
    return doc.title, doc.text


def build_script(item) -> tuple[str, str, str | None]:
    """Return (title, text to read aloud, note if the full content was unavailable)."""
    is_post = item["url"].startswith(("https://x.com/", "https://twitter.com/"))
    post = clean_for_speech(item["post_text"])
    title, body = (None, None) if is_post else extract(item["url"])
    host = (urllib.parse.urlparse(item["url"]).hostname or item["url"]).removeprefix("www.")
    if body:
        title = title or host
        intro = f"{title}. Saved from {item['source']}."
        if post:
            intro += f"\nThe post said: {post}\nHere is the article."
        return title, f"{intro}\n{clean_for_speech(body)}", None
    if post:
        title = post[:70]
        note = None if is_post else f"Could not read the linked page on {host}."
        ending = f"\nThe linked page on {host} could not be read, so check it yourself." if note else ""
        return title, f"A post saved from {item['source']}.\n{post}{ending}", note
    note = f"Could not read {host}."
    return f"Unreadable: {title or host}", f"A link you saved from {host} could not be read. It may be paywalled, or need a browser.", note


# --- Audio and feed --------------------------------------------------------

_model = None


def render_mp3(text: str, out: Path) -> float:
    """Synthesize text to MP3 and return its length in seconds."""
    global _model
    import numpy as np
    import soundfile as sf

    if _model is None:
        from mlx_audio.tts.utils import load_model
        _model = load_model(TTS_MODEL)
    gap = np.zeros(int(SAMPLE_RATE * 0.5))
    parts = []
    for result in _model.generate(text=text, voice=VOICE, speed=1.0, lang_code="a", split_pattern=r"\n+"):
        parts += [np.array(result.audio), gap]
    audio = np.concatenate(parts)
    sf.write(out, audio, SAMPLE_RATE, format="MP3")
    return len(audio) / SAMPLE_RATE


def process_pending(db) -> None:
    for item in db.execute("SELECT * FROM items WHERE status='pending' ORDER BY added_at").fetchall():
        try:
            title, script, note = build_script(item)
            name = f"{secrets.token_urlsafe(18)}.mp3"
            seconds = render_mp3(script, FEED_DIR / name)
        except Exception as exc:  # leave it pending so the next run retries
            print(f"Failed, will retry: {item['url']}: {exc}", file=sys.stderr)
            continue
        db.execute(
            "UPDATE items SET status='done', title=?, note=?, mp3=?, bytes=?, seconds=?, published_at=? WHERE id=?",
            (title, note, name, (FEED_DIR / name).stat().st_size, seconds, time.time(), item["id"]),
        )
        db.commit()
        print(f"Episode: {title} ({seconds / 60:.1f} min)" + (f" [{note}]" if note else ""))


def write_feed(db) -> Path:
    entries = []
    for row in db.execute("SELECT * FROM items WHERE status='done' ORDER BY published_at DESC"):
        summary = f"{row['note']} " if row["note"] else ""
        entries.append(f"""<item>
  <title>{escape(row['title'])}</title>
  <guid isPermaLink="false">{escape(row['id'])}</guid>
  <description>{escape(summary + row['url'])}</description>
  <pubDate>{formatdate(row['published_at'])}</pubDate>
  <enclosure url="{escape(f"{BASE_URL}/{row['mp3']}", {'"': '&quot;'})}" length="{row['bytes']}" type="audio/mpeg"/>
  <itunes:duration>{round(row['seconds'])}</itunes:duration>
</item>""")
    body = "\n".join(entries)
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>My Bookmarks</title>
  <link>{escape(BASE_URL)}</link>
  <description>Saved links, read in full.</description>
  <language>en</language>
  <itunes:block>Yes</itunes:block>
{body}
</channel>
</rss>
"""
    path = FEED_DIR / "feed.xml"
    path.write_text(feed, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("add").add_argument("url")
    sub.add_parser("x-auth")
    sub.add_parser("run")
    args = parser.parse_args()

    if args.command == "x-auth":
        x_auth()
        return
    db = connect()
    if args.command == "add":
        added = add_item(db, f"link:{args.url}", "your queue", args.url)
        print("Queued." if added else "Already seen.")
        return
    try:
        sync_x(db)
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"X sync failed, continuing with the queue: {exc}", file=sys.stderr)
    process_pending(db)
    print(f"Feed: {write_feed(db)}")


if __name__ == "__main__":
    main()
