import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import wavelink
from discord.ext import commands

from music import MAX_QUEUE, Music


def track(name="Test song"):
    return wavelink.Playable({
        "encoded": "test", "info": {
            "identifier": name, "isSeekable": True, "author": "Artist",
            "length": 180000, "isStream": False, "position": 0,
            "title": name, "uri": "https://www.youtube.com/watch?v=test",
            "sourceName": "youtube", "artworkUrl": None, "isrc": None,
        }, "pluginInfo": {}, "userData": {},
    })


class MusicTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"LAVALINK_URI": "http://localhost:2333", "LAVALINK_PASSWORD": "test"})
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
        first, second = track(), track("Second")
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[first, second])):
            await self.cog.enqueue(self.ctx, "song")
        self.player.play.assert_awaited_once_with(first)
        self.assertEqual(len(self.player.queue), 0)

    async def test_playlist_order_and_queue_cap(self):
        playlist = MagicMock(spec=wavelink.Playlist)
        playlist.tracks = [track(str(i)) for i in range(MAX_QUEUE + 10)]
        playlist.__len__.return_value = len(playlist.tracks)
        self.player.current = track("Already playing")
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=playlist)):
            await self.cog.enqueue(self.ctx, "https://open.spotify.com/playlist/test")
        self.assertEqual(len(self.player.queue), MAX_QUEUE)
        self.assertEqual(self.player.queue[0].title, "0")
        self.assertEqual(self.player.queue[-1].title, "199")
        self.player.play.assert_not_awaited()
        self.assertIn("10 tracks were omitted", self.ctx.reply.call_args.args[0])

    async def test_radio_seed_and_off_preserves_requested_queue(self):
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[track()])):
            await self.cog.enqueue(self.ctx, "song", radio=True)
        self.assertEqual(self.player.autoplay, wavelink.AutoPlayMode.enabled)
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

    async def test_failure_stops_radio_and_only_notifies_once(self):
        self.player.music_failed = False
        self.player.music_channel = SimpleNamespace(send=AsyncMock())
        self.player.queue.put(track())
        self.player.auto_queue.put(track())
        payload = SimpleNamespace(player=self.player)
        await asyncio.gather(self.cog.on_wavelink_track_exception(payload), self.cog.on_wavelink_track_exception(payload))
        self.player.disconnect.assert_awaited_once()
        self.player.music_channel.send.assert_awaited_once()
        self.assertEqual(self.player.autoplay, wavelink.AutoPlayMode.disabled)
        self.assertFalse(self.player.soundcloud_radio)
        self.assertEqual(len(self.player.queue) + len(self.player.auto_queue), 0)

    async def test_soundcloud_radio_avoids_repeats_and_prioritizes_queue(self):
        self.player.soundcloud_radio = True
        self.player.connected = True
        self.player.guild = SimpleNamespace(id=1)
        self.player.radio_query = "jazz"
        self.player.radio_seen = {"played"}
        payload = SimpleNamespace(player=self.player, reason="finished", track=track("played"))
        fresh = track("fresh")
        with patch("music.wavelink.Playable.search", AsyncMock(return_value=[track("played"), fresh])) as search:
            await self.cog.on_wavelink_track_end(payload)
            self.player.play.assert_awaited_with(fresh)
            search.assert_awaited_once_with("jazz", source="scsearch")
        requested = track("requested")
        self.player.queue.put(requested)
        with patch("music.wavelink.Playable.search", AsyncMock()) as search:
            await self.cog.on_wavelink_track_end(payload)
            search.assert_not_awaited()
            self.player.play.assert_awaited_with(requested)

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
