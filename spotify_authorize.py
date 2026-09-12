"""One-time Spotify PKCE authorization helper for the Discord bot."""
import base64
import hashlib
import json
import secrets
import ssl
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import certifi


CLIENT_ID = "808a8a8173bd4cb39bd5a90af6f7f5fa"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"
STATE = secrets.token_urlsafe(24)
VERIFIER = secrets.token_urlsafe(64)
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()
).rstrip(b"=").decode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get("state", [""])[0] != STATE or "code" not in query:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization failed or was cancelled.")
            return
        body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": VERIFIER,
        }).encode()
        request = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        context = ssl.create_default_context(cafile=certifi.where())
        token = json.load(urllib.request.urlopen(request, timeout=30, context=context))
        refresh = token.get("refresh_token", "")
        html = f"""<!doctype html><meta charset=utf-8><title>Spotify authorized</title>
        <style>body{{font:18px system-ui;max-width:720px;margin:60px auto;padding:20px}}
        textarea{{width:100%;height:110px}}button{{font-size:18px;padding:10px}}</style>
        <h1>Spotify authorized</h1><p>Copy this refresh token into Railway as
        <b>SPOTIFY_REFRESH_TOKEN</b>. Keep it private.</p>
        <textarea id=t readonly>{refresh}</textarea><br><button onclick="navigator.clipboard.writeText(t.value)">Copy token</button>"""
        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


params = urllib.parse.urlencode({
    "client_id": CLIENT_ID,
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPES,
    "code_challenge_method": "S256",
    "code_challenge": CHALLENGE,
    "state": STATE,
})
print("AUTH_URL=https://accounts.spotify.com/authorize?" + params, flush=True)
HTTPServer(("127.0.0.1", 8888), Handler).handle_request()
