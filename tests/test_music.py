import asyncio
import os
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import wavelink
from discord.ext import commands

from music import MAX_QUEUE, Music


def track(name="Test song"):
    return wavelink.Playable({
        "encoded": f"test:{name}", "info": {
            "identifier": name, "isSeekable": True, "author": "Artist",
            "length": 180000, "isStream": False, "position": 0,
            "title": name, "uri": "https://www.youtube.com/watch?v=test",
            "sourceName": "youtube", "artworkUrl": None, "isrc": None,
        }, "pluginInfo": {}, "userData": {},
    })


class MusicTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"LAVALINK_URI": "http://localhost:2333", "LAVALINK_PASSWORD": "test", "YTDLP_DIRECT_STREAM": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cog = Music(MagicMock())
        self.player = MagicMock(spec=wavelink.Player)
        self.player.queue = wavelink.Queue()
        self.player.auto_queue = wavelink.Queue()
        self.player.current = None
        self.player.autoplay = wavelink.AutoPlayMode.partial
        self.player.play = AsyncMock()
        self.player.channel = SimpleNamespace(id=100, connect=AsyncMock())
        self.ctx = MagicMock()
        self.ctx.guild = SimpleNamespace(id=1)
        self.ctx.author.voice.channel = self.player.channel
        self.ctx.voice_client = self.player
        self.ctx.reply = AsyncMock()

    async def test_search_plays_first_result_and_leaves_other_results_out(self):
        first, second = track("Song"), track("Song alternate")
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[first, second])):
            await self.cog.enqueue(self.ctx, "song")
        self.player.play.assert_awaited_once_with(first)
        self.assertEqual(len(self.player.queue), 0)
        self.assertEqual(list(self.player.music_fallbacks[first.identifier]), [second])

    async def test_failed_search_result_uses_hidden_matching_fallback(self):
        first, second = track("Stateside"), track("Stateside alternate")
        self.player.music_recovering = False
        self.player.music_failures = 0
        self.player.music_channel = SimpleNamespace(send=AsyncMock())
        self.player.music_fallbacks = {first.identifier: deque([second])}

        await self.cog.on_wavelink_track_exception(SimpleNamespace(player=self.player, track=first))

        self.player.play.assert_awaited_once_with(second)
        self.player.disconnect.assert_not_awaited()
        self.player.music_channel.send.assert_awaited_once()

    async def test_playlist_order_and_queue_cap(self):
        playlist = MagicMock(spec=wavelink.Playlist)
        playlist.tracks = [track(str(i)) for i in range(MAX_QUEUE + 10)]
        playlist.__len__.return_value = len(playlist.tracks)
        self.player.current = track("Already playing")
        with patch.object(self.cog, "spotify_tracks", AsyncMock(return_value=playlist.tracks)):
            await self.cog.enqueue(self.ctx, "https://open.spotify.com/playlist/test")
        self.assertEqual(len(self.player.queue), MAX_QUEUE)
        self.assertEqual(self.player.queue[0].title, "0")
        self.assertEqual(self.player.queue[-1].title, "199")
        self.player.play.assert_not_awaited()
        self.assertIn("10 tracks were omitted", self.ctx.reply.call_args.args[0])

    async def test_radio_seed_and_off_preserves_requested_queue(self):
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[track()])):
            await self.cog.enqueue(self.ctx, "song", radio=True)
        self.assertTrue(self.player.recommendation_radio)
        self.assertEqual(self.player.autoplay, wavelink.AutoPlayMode.disabled)
        self.player.queue.put(track("Requested"))
        self.player.auto_queue.put(track("Recommended"))
        await Music.radio.callback(self.cog, self.ctx, query="off")
        self.assertEqual(self.player.autoplay, wavelink.AutoPlayMode.partial)
        self.assertEqual(len(self.player.queue), 1)
        self.assertEqual(len(self.player.auto_queue), 0)

    async def test_wrong_voice_channel_rejected(self):
        self.ctx.author.voice.channel = SimpleNamespace(id=200)
        with self.assertRaises(commands.CheckFailure):
            await self.cog.cog_check(self.ctx)

    async def test_move_during_search_does_not_enqueue(self):
        async def search(*args, **kwargs):
            self.ctx.author.voice.channel = SimpleNamespace(id=200)
            return [track()]
        with patch("music.wavelink.Playable.search", search):
            with self.assertRaises(commands.CheckFailure):
                await self.cog.enqueue(self.ctx, "song")
        self.player.play.assert_not_awaited()
        self.assertEqual(len(self.player.queue), 0)

    async def test_missing_config_and_dms_have_helpful_errors(self):
        with patch.dict(os.environ, {"LAVALINK_URI": ""}):
            with self.assertRaisesRegex(commands.CheckFailure, "server first"):
                await self.cog.cog_check(self.ctx)
        self.ctx.guild = None
        with self.assertRaisesRegex(commands.CheckFailure, "inside a server"):
            await self.cog.cog_check(self.ctx)

    async def test_empty_search_does_not_connect(self):
        self.ctx.voice_client = None
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[])):
            await self.cog.enqueue(self.ctx, "missing song")
        self.ctx.author.voice.channel.connect.assert_not_called()

    async def test_commands_share_lock_and_release_after_failed_recheck(self):
        await self.cog.cog_before_invoke(self.ctx)
        pending = asyncio.create_task(self.cog.cog_before_invoke(self.ctx))
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        await self.cog.cog_after_invoke(self.ctx)
        await pending
        await self.cog.cog_after_invoke(self.ctx)
        self.ctx.author.voice.channel = None
        with self.assertRaises(commands.CheckFailure):
            await self.cog.cog_before_invoke(self.ctx)
        self.assertFalse(self.cog.locks[1].locked())

    async def test_node_errors_are_user_facing(self):
        await self.cog.cog_command_error(self.ctx, wavelink.InvalidNodeException())
        self.assertIn("unavailable", self.ctx.reply.call_args.args[0])

    async def test_failure_skips_bad_mirror_and_continues_playlist(self):
        self.player.music_recovering = False
        self.player.music_failures = 0
        self.player.music_channel = SimpleNamespace(send=AsyncMock())
        next_track = track("Next")
        self.player.queue.put(next_track)
        self.player.auto_queue.put(track())
        payload = SimpleNamespace(player=self.player)
        await self.cog.on_wavelink_track_exception(payload)
        self.player.play.assert_awaited_once_with(next_track)
        self.player.disconnect.assert_not_awaited()
        self.player.music_channel.send.assert_awaited_once()

    async def test_failure_limit_stops_playback(self):
        self.player.music_recovering = False
        self.player.music_failures = 10
        self.player.music_channel = SimpleNamespace(send=AsyncMock())
        self.player.queue.put(track())
        await self.cog.on_wavelink_track_exception(SimpleNamespace(player=self.player))
        self.player.disconnect.assert_awaited_once()
        self.assertEqual(len(self.player.queue), 0)

    async def test_failed_youtube_stream_uses_another_youtube_result(self):
        failed = track("Stateside")
        failed._author = "PinkPantheress - Topic"
        mirror = track("Stateside alternate")
        mirror._author = "PinkPantheress"
        mirror._source = "youtube"
        self.player.music_recovering = False
        self.player.music_failures = 0
        self.player.music_channel = SimpleNamespace(send=AsyncMock())

        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[mirror])) as search:
            await self.cog.on_wavelink_track_exception(SimpleNamespace(player=self.player, track=failed))

        search.assert_awaited_once_with("PinkPantheress - Stateside", source="ytsearch")
        self.player.play.assert_awaited_once_with(mirror)
        self.player.music_channel.send.assert_awaited_once()

    async def test_youtube_recovery_never_retries_the_same_upload(self):
        failed = track("Stateside")
        failed._source = "youtube"
        failed._author = "PinkPantheress"
        already_failed = track("Stateside alternate")
        fresh = track("Stateside official audio")
        already_failed._author = "PinkPantheress"
        fresh._author = "PinkPantheress"
        self.player.music_recovering = False
        self.player.music_failures = 0
        self.player.music_failed_tracks = {already_failed.identifier}
        self.player.music_channel = SimpleNamespace(send=AsyncMock())

        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[failed, already_failed, fresh])):
            await self.cog.on_wavelink_track_exception(SimpleNamespace(player=self.player, track=failed))

        self.player.play.assert_awaited_once_with(fresh)
        self.assertEqual(self.player.music_failed_tracks, {failed.identifier, already_failed.identifier})

    async def test_youtube_uses_ytdlp_signed_http_stream(self):
        source = track("Official song")
        stream = track("signed audio")
        stream._source = "http"
        with patch.dict(os.environ, {"YTDLP_DIRECT_STREAM": "true"}), \
             patch.dict(self.cog.play_track.__globals__, {"cache_audio": AsyncMock(return_value="http://discord-quote-bot:8080/internal/audio/track.webm")}), \
             patch("music.wavelink.Playable.search", AsyncMock(return_value=[stream])) as search:
            await self.cog.play_track(self.player, source)
        search.assert_awaited_once_with("http://discord-quote-bot:8080/internal/audio/track.webm")
        self.player.play.assert_awaited_once_with(stream)
        self.assertEqual(self.player.music_originals[stream.identifier], source)

    async def test_recommendation_radio_avoids_repeats_and_prioritizes_queue(self):
        self.player.recommendation_radio = True
        self.player.connected = True
        self.player.guild = SimpleNamespace(id=1)
        self.player.radio_query = "jazz"
        self.player.radio_seen = {"played"}
        payload = SimpleNamespace(player=self.player, reason="finished", track=track("played"))
        fresh = track("fresh")
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[track("played"), fresh])) as search:
            await self.cog.on_wavelink_track_end(payload)
            self.player.play.assert_awaited_with(fresh)
        search.assert_awaited_once_with("jazz", source="ytsearch")
        requested = track("requested")
        self.player.queue.put(requested)
        with patch("music.wavelink.Playable.search", AsyncMock()) as search:
            await self.cog.on_wavelink_track_end(payload)
            search.assert_not_awaited()
            self.player.play.assert_awaited_with(requested)

    async def test_recommended_radio_skips_repeats_and_spreads_artists(self):
        def upload(artist, name, ident, length=203000):
            t = track(ident)
            t._title, t._author, t._length = f"{artist} - {name}", artist, length
            return t
        self.player.recommendation_radio = True
        self.player.connected = True
        self.player.guild = SimpleNamespace(id=1)
        self.player.station_seeds = deque()
        self.player.station_name = None
        self.player.radio_seen = {"seed"}
        self.cog.reset_radio(self.player, "Dua Lipa", None)
        self.cog.remember(self.player, upload("Dua Lipa", "Levitating", "seed"))
        songs = [("Dua Lipa - Levitating", 203000, 1), ("Dua Lipa - Cool", 209000, 1),
                 ("Dua Lipa - Hallucinate", 208000, 1), ("Sia - The Greatest", 210000, 2),
                 ("Katy Perry - Roar", 223000, 3), ("Tate McRae - greedy", 131000, 4),
                 ("OneRepublic - Sunshine", 180000, 5)]
        lengths = {query: length for query, length, _ in songs}
        self.cog.recommender.for_query = AsyncMock(return_value=(songs, "songs like Dua Lipa"))
        self.cog.recommender.similar_to = AsyncMock(return_value=[])

        async def search(query, source):
            artist, _, name = query.partition(" - ")
            return [upload(artist, name, query, lengths[query])]
        with patch("music.wavelink.Playable.search", AsyncMock(side_effect=search)):
            picked = await self.cog.pick_recommendation(self.player)
        # Levitating already played; Dua Lipa was just heard, so another artist comes first.
        self.assertEqual(picked.title, "Sia - The Greatest")
        self.assertEqual(self.player.radio_label, "songs like Dua Lipa")

    async def test_radio_uses_prefetched_song_without_searching(self):
        self.player.recommendation_radio = True
        self.player.connected = True
        self.player.guild = SimpleNamespace(id=1)
        self.player.radio_seen = {"played"}
        ready = track("ready")
        self.player.radio_next = ready
        payload = SimpleNamespace(player=self.player, reason="finished", track=track("played"))
        with patch("music.wavelink.Playable.search", AsyncMock()) as search:
            await self.cog.on_wavelink_track_end(payload)
        search.assert_not_awaited()
        self.player.play.assert_awaited_with(ready)

    async def test_stop_disables_radio_and_disconnects(self):
        await Music.stop.callback(self.cog, self.ctx)
        self.assertEqual(self.player.autoplay, wavelink.AutoPlayMode.disabled)
        self.player.disconnect.assert_awaited_once()

    async def test_clear_keeps_current_song_and_removes_both_queues(self):
        current = track()
        self.player.current = current
        self.player.queue.put(track())
        self.player.auto_queue.put(track())
        await Music.clear.callback(self.cog, self.ctx)
        self.assertIs(self.player.current, current)
        self.assertEqual(len(self.player.queue) + len(self.player.auto_queue), 0)

    async def test_invalid_volume_does_not_reach_player(self):
        with self.assertRaises(commands.BadArgument):
            await Music.volume.callback(self.cog, self.ctx, 101)
        self.player.set_volume.assert_not_called()

    async def test_extension_loads_without_music_configuration(self):
        from bot import QuoteBot, intents
        with patch.dict(os.environ, {"LAVALINK_URI": ""}):
            async with QuoteBot(command_prefix="!", intents=intents) as bot:
                await bot.setup_hook()
                for name in ("play", "radio", "queue", "stop", "volume"):
                    self.assertIsNotNone(bot.get_command(name))
                self.assertIsNone(bot.get_cog("Music").connect_task)


if __name__ == "__main__":
    unittest.main()
