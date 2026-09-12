import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from collections import deque

from music_selection import normalize_query, provider, select_tracks, station_name
from music import Music
from spotify_resolver import parse_spotify_url, track_query


def candidate(title, author="Norah Jones", length=210000):
    return SimpleNamespace(title=title, author=author, length=length, is_stream=False, identifier=title)


class SelectionTests(unittest.TestCase):
    def test_spotify_urls_and_track_queries(self):
        self.assertEqual(parse_spotify_url("https://open.spotify.com/playlist/abc?si=1"), ("playlist", "abc"))
        self.assertEqual(parse_spotify_url("https://open.spotify.com/intl-fr/track/xyz"), ("track", "xyz"))
        self.assertIsNone(parse_spotify_url("https://open.spotify.com.evil.invalid/track/xyz"))
        self.assertEqual(track_query({"name": "Song", "artists": [{"name": "Artist"}]}), "Artist Song")
        self.assertIsNone(track_query({"type": "episode", "name": "Podcast", "artists": []}))

    def test_user_station_intents(self):
        self.assertEqual(station_name("white girl pop"), "pop")
        self.assertEqual(station_name("2015 most popular"), "2015 hits")
        self.assertEqual(station_name("popular songs"), "pop")
        self.assertIsNone(station_name("Taylor Swift Blank Space"))

    def test_reject_previews_remixes_compilations_and_wrong_matches(self):
        good = candidate("Come Away With Me")
        tracks = [candidate("Come Away With Me Preview"), candidate("Come Away With Me Remix"),
                  candidate("Come Away With Me", length=30000), candidate("Jazz mix", length=3600000),
                  candidate("White Girl", author="Shy Glizzy"), good]
        self.assertEqual(select_tracks(tracks, "Norah Jones Come Away With Me", strict=True), [good])

    def test_explicit_remix_is_allowed(self):
        remix = candidate("Come Away With Me Remix")
        self.assertEqual(select_tracks([remix], "Norah Jones Come Away With Me remix", strict=True), [remix])

    def test_discord_link_wrappers_and_host_validation(self):
        url = "https://www.youtube.com/watch?v=Y3jq_WIHP9k"
        self.assertEqual(normalize_query("[YouTube](" + url.replace("_", r"\_") + ")"), url)
        self.assertEqual(normalize_query("<" + url + ">"), url)
        self.assertEqual(provider(url), "YouTube")
        self.assertEqual(provider("https://youtube.com.evil.invalid/video"), "This source")


class StationTests(unittest.IsolatedAsyncioTestCase):
    async def test_station_tries_next_song_after_bad_match(self):
        cog = Music(None)
        good = candidate("Come Away With Me")
        seeds = deque(["Bill Evans Peace Piece", "Norah Jones Come Away With Me"])
        with patch("music.wavelink.Playable.search", AsyncMock(side_effect=[[candidate("Unrelated")], [good]])) as search:
            self.assertEqual(await cog.station_track(seeds, set()), [good])
            self.assertEqual(search.await_count, 2)

    async def test_station_search_is_bounded(self):
        seeds = deque([str(n) for n in range(12)])
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[])) as search:
            self.assertEqual(await Music(None).station_track(seeds, set()), [])
            self.assertEqual(search.await_count, 4)
