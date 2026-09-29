"""Song recommendations for radio, from Deezer's public catalog API (no key needed).

Deezer only supplies *which* songs to play next ("Artist - Title" plus length).
Playback still goes through Lavalink search, so this never streams from Deezer.
"""
import asyncio
import logging
import random
import re
import ssl

import aiohttp
import certifi

from music_selection import tokens

log = logging.getLogger(__name__)
API = "https://api.deezer.com"
# Alternate versions that make a radio feel cheap; skipped unless asked for.
ALT_VERSIONS = {"slowed", "reverb", "sped", "nightcore", "remix", "karaoke", "instrumental",
                "cover", "mix", "lofi", "8d", "acoustic", "live", "extended", "edit", "mashup"}
JUNK = re.compile(
    r"[\(\[][^\)\]]*(official|audio|video|lyric|visualizer|hq|hd|explicit|clean)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def clean(text):
    """Strip upload noise such as '(Official Video)' before looking a song up."""
    text = JUNK.sub(" ", text or "")
    text = re.sub(r"\s+-\s+Topic$", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def song_key(artist, title):
    """Identify a song across different uploads, so radio never repeats it."""
    title = re.sub(r"[\(\[].*?[\)\]]", " ", title or "")
    title = re.split(r"\s+(feat\.?|ft\.?|with)\s+", title, flags=re.IGNORECASE)[0]
    words = sorted(tokens(title))
    if not words:
        return None
    return " ".join(words) + "|" + " ".join(sorted(tokens(artist or "")))


def upload_key(track):
    """song_key for a Lavalink track whose title may be 'Artist - Title'."""
    parts = re.split(r"\s+[-–—]\s+", track.title, maxsplit=1)
    artist, title = (parts[0], parts[1]) if len(parts) == 2 else (track.author, track.title)
    return song_key(clean(artist), clean(title))


class Recommender:
    def __init__(self, timeout=8):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = None

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get(self, path, **params):
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))
            self.session = aiohttp.ClientSession(timeout=self.timeout, connector=connector)
        try:
            async with self.session.get(f"{API}{path}", params=params) as response:
                if response.status != 200:
                    return []
                body = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            log.warning("Recommendation lookup failed for %s", path)
            return []
        if not isinstance(body, dict) or "error" in body:
            return []
        return body.get("data") or []

    @staticmethod
    def songs(items):
        """Deezer tracks -> [(search query, length ms, artist id)]."""
        found = []
        for item in items:
            artist = (item.get("artist") or {})
            if not item.get("title") or not artist.get("name"):
                continue
            if tokens(item["title"] + " " + artist["name"]) & ALT_VERSIONS:
                continue
            found.append((f"{artist['name']} - {item['title']}", int(item.get("duration") or 0) * 1000, artist.get("id")))
        return found

    async def artist_mix(self, artist_id, limit=25):
        """Deezer's artist radio: the artist plus similar artists, already mixed."""
        return self.songs(await self.get(f"/artist/{artist_id}/radio", limit=limit))

    async def similar_to(self, artist, title):
        """Songs like a specific track: find it, then use its artist's radio."""
        artist, title = clean(artist), clean(title)
        found = await self.get("/search", q=f"{artist} {title}".strip(), limit=5)
        if not found:
            found = await self.get("/search", q=title, limit=5)
        artist_id = found[0]["artist"]["id"] if found and found[0].get("artist") else None
        if artist_id is None and artist:
            artists = await self.get("/search/artist", q=artist, limit=1)
            artist_id = artists[0]["id"] if artists else None
        return await self.artist_mix(artist_id) if artist_id else []

    async def for_query(self, query):
        """Interpret free text as an artist, a song, or a mood/genre.

        Returns (songs, label) where label describes what radio is based on.
        """
        wanted = tokens(query)
        if not wanted:
            return [], None
        # 1. An artist name ("drake"): the most-followed artist with that exact name.
        #    The fan floor skips tiny acts that happen to be called "Sad Songs".
        artists = [a for a in await self.get("/search/artist", q=query, limit=5)
                   if tokens(a.get("name", "")) == wanted and (a.get("nb_fan") or 0) >= 5000]
        if artists:
            best = max(artists, key=lambda a: a.get("nb_fan") or 0)
            return await self.artist_mix(best["id"]), f"songs like {best['name']}"
        # 2. A song that names its artist ("sza snooze"). Requiring the artist
        #    keeps moods like "sad songs" from matching a track called that.
        hits = await self.get("/search", q=query, limit=10)
        for hit in hits:
            artist, title = tokens(hit["artist"]["name"]), tokens(hit["title"])
            if artist and artist <= wanted and len(wanted & (artist | title)) / len(wanted) >= 0.75:
                return await self.like_song(hit)
        # 3. A mood or genre with an editor-curated playlist ("chill jazz", "workout").
        found = await self.mood(query, curated_only=True)
        if found:
            return found, f"{query} mix"
        # 4. A well-known song title on its own ("blinding lights").
        titled = [h for h in hits if tokens(h["title"]) == wanted]
        if titled:
            song = max(titled, key=lambda h: h.get("rank") or 0)
            if (song.get("rank") or 0) >= 300000:
                return await self.like_song(song)
        # 5. Anything else: any matching playlist, then the top search hit.
        found = await self.mood(query)
        if found:
            return found, f"{query} mix"
        if hits:
            song = max(titled or hits[:3], key=lambda h: h.get("rank") or 0)
            return await self.like_song(song)
        return [], None

    async def like_song(self, song):
        mix = await self.artist_mix(song["artist"]["id"])
        return mix, f"songs like {song['artist']['name']} - {song['title']}"

    async def mood(self, query, limit=60, curated_only=False):
        """Mood/genre text ('sad songs', 'chill jazz') -> tracks from a popular matching playlist."""
        playlists = await self.get("/search/playlist", q=query, limit=10)
        playlists = [p for p in playlists if (p.get("nb_tracks") or 0) >= 15]
        # Deezer's editor-curated playlists are far cleaner than user uploads.
        curated = [p for p in playlists if "deezer" in ((p.get("user") or {}).get("name") or "").lower()]
        pool = curated if curated_only else (curated or playlists)
        # A playlist named exactly what was asked ("Workout") beats "Metal Workout".
        choices = [p for p in pool if tokens(p.get("title", "")) == tokens(query)] or pool[:3]
        if not choices:
            return []
        choice = random.choice(choices)
        found = self.songs(await self.get(f"/playlist/{choice['id']}/tracks", limit=limit))
        random.shuffle(found)
        return found
