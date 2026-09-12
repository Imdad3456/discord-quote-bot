"""Resolve Spotify links to searchable track names with a user's refresh token."""
import asyncio
import os
import time
from urllib.parse import urlparse

import aiohttp


SPOTIFY_HOSTS = {"open.spotify.com", "www.open.spotify.com"}


def parse_spotify_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in SPOTIFY_HOSTS:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0].startswith("intl-"):
        parts = parts[1:]
    if len(parts) != 2 or parts[0] not in {"track", "album", "playlist"}:
        return None
    return parts[0], parts[1]


def track_query(item):
    if not isinstance(item, dict) or item.get("type") not in (None, "track"):
        return None
    name = item.get("name")
    artists = [artist.get("name") for artist in item.get("artists", []) if artist.get("name")]
    if not name or not artists:
        return None
    return f"{' '.join(artists)} {name}"


class SpotifyResolver:
    def __init__(self):
        self.access_token = None
        self.expires_at = 0
        self.lock = asyncio.Lock()

    @property
    def configured(self):
        return bool(os.getenv("SPOTIFY_CLIENT_ID") and os.getenv("SPOTIFY_REFRESH_TOKEN"))

    async def token(self, session):
        if self.access_token and time.monotonic() < self.expires_at:
            return self.access_token
        async with self.lock:
            if self.access_token and time.monotonic() < self.expires_at:
                return self.access_token
            async with session.post("https://accounts.spotify.com/api/token", data={
                "grant_type": "refresh_token",
                "refresh_token": os.environ["SPOTIFY_REFRESH_TOKEN"],
                "client_id": os.environ["SPOTIFY_CLIENT_ID"],
            }) as response:
                if response.status != 200:
                    raise RuntimeError(f"Spotify token refresh returned {response.status}")
                payload = await response.json()
            self.access_token = payload["access_token"]
            self.expires_at = time.monotonic() + max(30, payload.get("expires_in", 3600) - 60)
            return self.access_token

    async def get(self, session, url):
        token = await self.token(session)
        async with session.get(url, headers={"Authorization": f"Bearer {token}"}) as response:
            if response.status == 401:
                self.access_token = None
            if response.status != 200:
                raise RuntimeError(f"Spotify API returned {response.status}")
            return await response.json()

    async def resolve(self, value, limit=200):
        parsed = parse_spotify_url(value)
        if not parsed:
            return None
        if not self.configured:
            raise RuntimeError("Spotify account access is not configured")
        kind, item_id = parsed
        base = "https://api.spotify.com/v1"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            if kind == "track":
                item = await self.get(session, f"{base}/tracks/{item_id}")
                return [query for query in [track_query(item)] if query]
            url = (f"{base}/albums/{item_id}/tracks?limit=50" if kind == "album"
                   else f"{base}/playlists/{item_id}/items?limit=50")
            queries = []
            while url and len(queries) < limit:
                page = await self.get(session, url)
                for entry in page.get("items", []):
                    item = entry.get("item", entry.get("track", entry)) if isinstance(entry, dict) else None
                    query = track_query(item)
                    if query:
                        queries.append(query)
                        if len(queries) == limit:
                            break
                url = page.get("next")
            return queries
