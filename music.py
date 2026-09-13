"""Per-server music queues and recommendation radio, backed by Lavalink v4."""
import asyncio
import logging
import os
import random
from collections import defaultdict, deque

import discord
import wavelink
from discord.ext import commands
from music_selection import STATIONS, normalize_query, provider, select_tracks, station_name
from spotify_resolver import SpotifyResolver, parse_spotify_url

log = logging.getLogger(__name__)
MAX_QUEUE = 200


def title(track):
    return discord.utils.escape_markdown(track.title[:120])


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.connect_task = None
        self.locks = defaultdict(asyncio.Lock)
        self.spotify = SpotifyResolver()

    async def cog_before_invoke(self, ctx):
        await self.locks[ctx.guild.id].acquire()
        try:
            await self.cog_check(ctx)
        except BaseException:
            self.locks[ctx.guild.id].release()
            raise

    async def cog_after_invoke(self, ctx):
        self.locks[ctx.guild.id].release()

    async def cog_load(self):
        if os.getenv("LAVALINK_URI") and os.getenv("LAVALINK_PASSWORD"):
            self.connect_task = asyncio.create_task(self.connect_node())

    async def cog_unload(self):
        if self.connect_task:
            self.connect_task.cancel()
            await asyncio.gather(self.connect_task, return_exceptions=True)

    async def connect_node(self):
        await self.bot.wait_until_ready()
        try:
            await wavelink.Pool.connect(client=self.bot, nodes=[wavelink.Node(
                uri=os.environ["LAVALINK_URI"],
                password=os.environ["LAVALINK_PASSWORD"],
                inactive_player_timeout=300,
            )])
        except Exception:
            log.exception("Music server connection failed; quote commands remain available.")

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Music commands only work inside a server.")
        if not os.getenv("LAVALINK_URI") or not os.getenv("LAVALINK_PASSWORD"):
            raise commands.CheckFailure("Music needs a server first. Set LAVALINK_URI and LAVALINK_PASSWORD (see README).")
        voice = getattr(ctx.author, "voice", None)
        if voice is None or voice.channel is None:
            raise commands.CheckFailure("Join a voice channel first.")
        if ctx.voice_client and ctx.voice_client.channel != voice.channel:
            raise commands.CheckFailure("Join my voice channel to control the music.")
        return True

    async def reply(self, ctx, text):
        await ctx.reply(text, mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    def player(self, ctx):
        if not isinstance(ctx.voice_client, wavelink.Player):
            raise commands.CheckFailure("Nothing is playing. Use `!play <song or link>` first.")
        return ctx.voice_client

    async def enqueue(self, ctx, query, radio=False):
        query = normalize_query(query)
        if not query:
            raise commands.BadArgument("Provide a song name or supported link.")
        async with ctx.typing():
            spotify_link = bool(parse_spotify_url(query))
            station = station_name(query)
            seeds = deque()
            if station:
                radio = True
                seed_list = STATIONS[station].copy()
                random.shuffle(seed_list)
                seeds.extend(seed_list)
                tracks = await self.station_track(seeds, set())
            elif spotify_link:
                tracks = await self.spotify_tracks(query)
            else:
                try:
                    tracks = await wavelink.Playable.search(
                        query, source=os.getenv("MUSIC_SEARCH_SOURCE", "scsearch")
                    )
                except wavelink.LavalinkLoadException as error:
                    source = provider(query)
                    log.warning("Track lookup failed for %s (%s)", source, type(error).__name__)
                    detail = {
                        "YouTube": "YouTube rejected this link on the music server. Its login/authentication setup needs attention; retrying this link will not fix that.",
                        "Spotify": "Spotify could not load this playlist/track. The server's Spotify credentials/token setup needs attention. No songs were added.",
                    }.get(source, "This source could not load that link. It may be unavailable or restricted.")
                    raise commands.BadArgument(detail) from error
                if not query.startswith(("https://", "http://")) and not isinstance(tracks, wavelink.Playlist):
                    tracks = select_tracks(tracks, query)
            if not tracks:
                await self.reply(ctx, "No tracks found. Try a song and artist name, or another supported link.")
                return
            # Recheck after the network search: the requester may have moved.
            await self.cog_check(ctx)
            player = ctx.voice_client
            if player is None:
                channel = ctx.author.voice.channel
                if not isinstance(channel, discord.VoiceChannel):
                    raise commands.CheckFailure("Please use a regular voice channel, not a Stage channel.")
                permissions = channel.permissions_for(ctx.guild.me)
                if not permissions.connect or not permissions.speak:
                    raise commands.CheckFailure("I need Connect and Speak permissions in your voice channel.")
                player = await channel.connect(cls=wavelink.Player, self_deaf=True)
                player.autoplay = wavelink.AutoPlayMode.partial
            player.music_failures = 0
            player.music_recovering = False
            player.music_channel = ctx.channel
            selected = tracks.tracks if isinstance(tracks, wavelink.Playlist) else (tracks if spotify_link else tracks[:1])
            room = max(0, MAX_QUEUE - len(player.queue))
            added = selected[:room]
            if not added:
                await self.reply(ctx, f"The queue is full ({MAX_QUEUE} songs). Skip or clear some first.")
                return
            if radio:
                player.autoplay = wavelink.AutoPlayMode.enabled
                player.soundcloud_radio = bool(station) or added[0].source == "soundcloud"
                player.station_seeds = seeds
                player.station_name = station
                player.radio_query = query if not query.startswith("http") else added[0].author
                player.radio_seen = {added[0].identifier}
                if player.soundcloud_radio:
                    player.autoplay = wavelink.AutoPlayMode.disabled
            if radio:
                player.auto_queue.clear()
                await player.play(added[0])
                player.queue.put(added[1:])
            else:
                player.queue.put(added)
            if not radio and player.current is None:
                await player.play(player.queue.get())
            suffix = f" Station: {station}. Fresh song selections follow your requested queue." if station else (" Radio will select more songs when the queue runs out." if radio else "")
            if len(added) < len(selected):
                suffix += f" Queue limit reached; {len(selected) - len(added)} tracks were omitted."
            await self.reply(ctx, f"Added {len(added)} song(s): {title(added[0])}.{suffix}")

    async def spotify_tracks(self, url):
        try:
            queries = await self.spotify.resolve(url, MAX_QUEUE)
        except (RuntimeError, asyncio.TimeoutError):
            log.exception("Spotify account lookup failed")
            raise commands.BadArgument(
                "Spotify could not read that link. Check the bot service's Spotify account variables, then redeploy."
            )
        if not queries:
            return []
        semaphore = asyncio.Semaphore(5)

        async def match(candidate):
            query, expected_length = candidate
            async with semaphore:
                try:
                    results = await wavelink.Playable.search(
                        query, source=os.getenv("MUSIC_SEARCH_SOURCE", "scsearch")
                    )
                except wavelink.LavalinkLoadException:
                    return None
                matches = select_tracks(results, query, strict=True, expected_length=expected_length)
                return matches[0] if matches else None

        matches = await asyncio.gather(*(match(candidate) for candidate in queries))
        return [track for track in matches if track is not None]

    async def station_track(self, seeds, seen):
        # Try a bounded number per refill; no infinite loop against blocked providers.
        for _ in range(min(4, len(seeds))):
            query = seeds.popleft()
            try:
                results = await wavelink.Playable.search(query, source=os.getenv("MUSIC_SEARCH_SOURCE", "scsearch"))
            except wavelink.LavalinkLoadException:
                continue
            matches = [t for t in select_tracks(results, query, strict=True) if t.identifier not in seen]
            if matches:
                return matches[:1]
        return []

    @commands.command(help="List curated radio stations.")
    async def stations(self, ctx):
        names = ", ".join(f"`{name}`" for name in STATIONS)
        await self.reply(ctx, f"**Radio stations:** {names}\nUse `!radio <station>`. A new station starts immediately; requested songs stay queued.")

    @commands.command(name="play", aliases=["p"], help="Play a song name, track URL, or playlist URL.")
    async def play(self, ctx, *, query: str):
        await self.enqueue(ctx, query)

    @commands.command(help="Radio from a song/artist/mood; !radio off disables recommendations.")
    async def radio(self, ctx, *, query: str = "on"):
        if query.lower() in ("on", "off"):
            player = self.player(ctx)
            enabled = query.lower() == "on"
            if enabled and player.current is None:
                raise commands.CheckFailure("Start radio with `!radio <song, artist, or mood>`.")
            player.autoplay = wavelink.AutoPlayMode.enabled if enabled else wavelink.AutoPlayMode.partial
            player.soundcloud_radio = bool(enabled and player.current.source == "soundcloud")
            if player.soundcloud_radio:
                player.autoplay = wavelink.AutoPlayMode.disabled
                player.radio_query = player.current.author
                player.radio_seen = {player.current.identifier}
                player.station_seeds = deque()
            if not enabled:
                player.auto_queue.clear()
            await self.reply(ctx, "Radio on: recommendations follow your queue." if enabled else "Radio off: only queued songs will play.")
        else:
            await self.enqueue(ctx, query, radio=True)

    @commands.command(aliases=["q"], help="Show the next ten queued songs.")
    async def queue(self, ctx):
        player = self.player(ctx)
        lines = [f"Now: {title(player.current)}" if player.current else "Nothing playing."]
        lines.extend(f"{i}. {title(track)}" for i, track in enumerate(list(player.queue)[:10], 1))
        radio_on = player.autoplay == wavelink.AutoPlayMode.enabled or getattr(player, "soundcloud_radio", False)
        lines.append(f"{len(player.queue)} queued · Radio {'on' if radio_on else 'off'}")
        await self.reply(ctx, "\n".join(lines))

    @commands.command(aliases=["np"], help="Show the current song.")
    async def nowplaying(self, ctx):
        player = self.player(ctx)
        await self.reply(ctx, f"Playing: {title(player.current)}" if player.current else "Nothing playing.")

    @commands.command(help="Skip the current song.")
    async def skip(self, ctx):
        await self.player(ctx).skip(force=True)
        await self.reply(ctx, "Skipped.")

    @commands.command(help="Pause playback.")
    async def pause(self, ctx):
        await self.player(ctx).pause(True)
        await self.reply(ctx, "Paused.")

    @commands.command(help="Resume playback.")
    async def resume(self, ctx):
        await self.player(ctx).pause(False)
        await self.reply(ctx, "Resumed.")

    @commands.command(help="Shuffle upcoming songs.")
    async def shuffle(self, ctx):
        self.player(ctx).queue.shuffle()
        await self.reply(ctx, "Queue shuffled.")

    @commands.command(help="Clear upcoming songs and turn radio off; keep the current song.")
    async def clear(self, ctx):
        player = self.player(ctx)
        player.soundcloud_radio = False
        player.autoplay = wavelink.AutoPlayMode.partial
        player.queue.clear()
        player.auto_queue.clear()
        await self.reply(ctx, "Queue cleared and radio turned off.")

    @commands.command(help="Set volume from 0 to 100.")
    async def volume(self, ctx, value: int):
        if not 0 <= value <= 100:
            raise commands.BadArgument("Volume must be between 0 and 100.")
        await self.player(ctx).set_volume(value)
        await self.reply(ctx, f"Volume: {value}%.")

    @commands.command(aliases=["leave", "disconnect"], help="Stop playback, discard the queue, and leave voice.")
    async def stop(self, ctx):
        player = self.player(ctx)
        player.soundcloud_radio = False
        player.autoplay = wavelink.AutoPlayMode.disabled
        await player.disconnect()
        await self.reply(ctx, "Stopped and left voice.")

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player):
        await player.disconnect()

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload):
        player = payload.player
        if player is None or getattr(player, "music_recovering", False):
            return
        player.music_recovering = True
        player.music_failures = getattr(player, "music_failures", 0) + 1
        try:
            if player.queue and player.music_failures <= 10:
                next_track = player.queue.get()
                if player.music_failures == 1 and getattr(player, "music_channel", None):
                    await player.music_channel.send(
                        "One unavailable mirror was skipped; continuing with the playlist.",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                await player.play(next_track)
                return
            player.soundcloud_radio = False
            player.autoplay = wavelink.AutoPlayMode.disabled
            player.queue.clear()
            player.auto_queue.clear()
            await player.disconnect()
            channel = getattr(player, "music_channel", None)
            if channel:
                await channel.send(
                    "Too many tracks were unavailable, so playback stopped. Try another playlist or song.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        finally:
            player.music_recovering = False

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload):
        if payload.player is not None:
            payload.player.music_failures = 0

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        player = payload.player
        if player is None or not getattr(player, "soundcloud_radio", False):
            return
        if payload.reason not in ("finished", "stopped"):
            return
        async with self.locks[player.guild.id]:
            if not player.connected or not player.soundcloud_radio:
                return
            if player.queue:
                next_track = player.queue.get()
            else:
                # Wavelink's native recommendations only support YouTube/Spotify.
                # SoundCloud radio uses fresh search results for the seed, then artist.
                candidates = []
                seeds = getattr(player, "station_seeds", None)
                queries = [] if getattr(player, "station_name", None) else list(dict.fromkeys([player.radio_query, payload.track.author]))
                if seeds is not None and len(seeds):
                    candidates = await self.station_track(seeds, player.radio_seen)
                for query in queries:
                    try:
                        results = await wavelink.Playable.search(query, source="scsearch")
                    except wavelink.WavelinkException:
                        continue
                    candidates = [t for t in select_tracks(results, query) if t.identifier not in player.radio_seen]
                    if candidates:
                        break
                if not candidates:
                    player.soundcloud_radio = False
                    player.autoplay = wavelink.AutoPlayMode.partial
                    await player.music_channel.send("Radio ran out of fresh matches. Start a new station with `!radio <artist or mood>`.", allowed_mentions=discord.AllowedMentions.none())
                    return
                next_track = candidates[0]
            if not player.connected or not player.soundcloud_radio:
                return
            player.radio_seen.add(next_track.identifier)
            await player.play(next_track)

    async def cog_command_error(self, ctx, error):
        error = getattr(error, "original", error)
        if isinstance(error, commands.MissingRequiredArgument):
            message = f"Usage: `!{ctx.command.qualified_name} {ctx.command.signature}`"
        elif isinstance(error, (commands.CheckFailure, commands.BadArgument)):
            message = str(error)
        elif isinstance(error, (wavelink.WavelinkException, asyncio.TimeoutError)):
            message = "The music server or source is unavailable. Try another link or ask the owner to check Lavalink."
        elif isinstance(error, discord.Forbidden):
            message = "I need permission to connect, speak, and send messages in these channels."
        else:
            log.error("Music command failed", exc_info=(type(error), error, error.__traceback__))
            message = "Music command failed. Try again; the bot owner can check the logs."
        await self.reply(ctx, message)


async def setup(bot):
    await bot.add_cog(Music(bot))
