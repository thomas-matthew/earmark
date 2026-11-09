"""Sign-in to the X API with OAuth 2 (PKCE). `earmark x-auth` runs this once in a browser;
the refresh token then keeps access alive. The token file is private to my user (mode 600)."""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ...common import web
from ...common.web import LoginExpired
from ...config import Settings

API = "https://api.x.com/2"
REDIRECT = "http://127.0.0.1:8723/callback"
SCOPES = "tweet.read users.read bookmark.read offline.access"


def _token_request(settings: Settings, fields: dict) -> dict:
    client_id = settings.secret("X_CLIENT_ID")
    if not client_id:
        raise LoginExpired("X")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    secret = settings.secret("X_CLIENT_SECRET")
    if secret:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    else:
        fields = {**fields, "client_id": client_id}
    status, body, _ = web.request(f"{API}/oauth2/token", headers, urllib.parse.urlencode(fields).encode())
    if status in (400, 401):
        raise LoginExpired("X")  # refresh token revoked or expired: run `earmark x-auth` again
    if status != 200:
        raise web.HttpError(status, f"{API}/oauth2/token")
    token = json.loads(body)
    token["expires_at"] = time.time() + token.get("expires_in", 0)
    return token


def _save(path: Path, token: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(token, f)


def access_token(settings: Settings) -> str:
    path = settings.x_token_path
    if not path.exists():
        raise LoginExpired("X")
    token = json.loads(path.read_text())
    if time.time() > token["expires_at"] - 120:
        token = _token_request(settings, {"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
        _save(path, token)  # X rotates refresh tokens, so the new one must be kept
    return token["access_token"]


def authorize(settings: Settings) -> None:
    client_id = settings.secret("X_CLIENT_ID")
    if not client_id:
        raise SystemExit("Add X_CLIENT_ID (and X_CLIENT_SECRET) to .env first.")
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(16)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": SCOPES,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
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
    print(f"Opening X to approve read-only access. If nothing opens, visit:\n{url}")
    webbrowser.open(url)
    HTTPServer(("127.0.0.1", 8723), Callback).handle_request()
    if result.get("state", [None])[0] != state or "code" not in result:
        raise SystemExit("Authorization failed or was declined.")
    _save(settings.x_token_path, _token_request(settings, {
        "grant_type": "authorization_code", "code": result["code"][0], "redirect_uri": REDIRECT, "code_verifier": verifier,
    }))
    print("Authorized.")
