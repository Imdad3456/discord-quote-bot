# Discord quote and music bot

The existing quote commands, quote cards, and daily quotes remain available.
Music uses a separate Lavalink v4 audio service and Wavelink for Discord control.
Text searches default to SoundCloud because YouTube can require login from hosted
servers. SoundCloud radio searches for new seed/artist matches, avoids repeats,
and stops when there are no fresh matches. Playback errors stop the session with
one notice, rather than cycling through failing recommendations.
Python 3.10+ is required. Music is optional: without the two Lavalink variables,
the bot starts normally and explains how to enable music when a music command is used.

## Music commands

Join a regular voice channel, then use:

| Command | Action |
| --- | --- |
| `!play Daft Punk One More Time` | Search and play the first result |
| `!play <track or playlist link>` | Queue a supported track or playlist |
| `!radio chill jazz` | Search for a seed and enable related-song autoplay |
| `!radio on` / `!radio off` | Enable/disable recommendations for the current session |
| `!queue` / `!q` | View the next ten requested songs |
| `!nowplaying` / `!np` | Show the current song |
| `!skip` | Skip the current song |
| `!pause` / `!resume` | Pause/resume |
| `!shuffle` | Shuffle upcoming requested songs |
| `!clear` | Clear upcoming songs and disable radio |
| `!volume 50` | Set volume from 0 to 100 |
| `!stop` / `!leave` | Discard the session and disconnect |

Each Discord server has its own queue, capped at 200 upcoming tracks. Commands
are restricted to listeners in the bot's voice channel. The bot leaves after
five minutes of inactivity. Queues are held in memory and do not survive restarts.
Requested songs take priority over radio recommendations. A new radio query adds
a seed to the queue; it does not interrupt the current song. Radio is related-track
autoplay, not Spotify's personalized radio or a natural-language DJ.

## Supported sources

The included configuration enables YouTube/YouTube Music, SoundCloud, Bandcamp,
Twitch, Vimeo, and Spotify metadata through LavaSrc. Source availability depends
on the hosting IP, region, provider restrictions, and upstream plugin changes.
No bot can promise every link will work.

Spotify tracks/playlists are matched to audio on YouTube, rather than streamed
from Spotify. Matches may differ or fail. Private and Spotify-generated playlists
are not guaranteed. Start with public playlists. Spotify credentials, when needed,
belong on the Lavalink service. Other services require additional plugins/configuration.
Arbitrary HTTP streams and local files are disabled in this shared-bot configuration.

## Local setup

1. Copy `.env.example` to `.env`. Set the existing Discord token and quotes channel.
2. Set a long random `LAVALINK_PASSWORD`, and set `LAVALINK_URI=http://localhost:2333`.
3. Install Docker, then run `docker compose up -d --build lavalink` from this folder.
4. Create a Python virtual environment and install `pip install -r requirements.txt`.
5. Run `python bot.py` in that environment.
6. Keep Message Content Intent enabled in the Discord Developer Portal. Give the
   bot View Channel, Send Messages, Connect, and Speak in the relevant channels,
   plus its existing quote-related permissions.

Lavalink handles audio: Python does not need FFmpeg or a local audio device.
If Spotify lookup requires credentials, create an application at
<https://developer.spotify.com/dashboard>, set `SPOTIFY_CLIENT_ID` and
`SPOTIFY_CLIENT_SECRET` in `.env`, then recreate the Lavalink container.
Never commit `.env` or paste the Discord token into chat.

## Railway setup

Keep the current Python bot service and quote-data volume. Add a second service
from this repository for Lavalink:

1. Set its Root Directory to `/deploy/lavalink`. Railway should detect the
   Dockerfile there. Leave the custom start command empty so the image starts Lavalink.
2. Set `LAVALINK_PASSWORD` on the new service. Add Spotify credentials if required.
3. Enable Railway private networking for the services. Set the bot service's
   `LAVALINK_URI` to `http://<lavalink-private-hostname>:2333`, using the hostname
   shown for your service, and set the same `LAVALINK_PASSWORD` on the bot.
4. Deploy both services. Check Lavalink logs for startup and plugin loading, and
   then check bot logs for the music connection. The Lavalink service must have
   outbound connectivity to Discord voice and music providers.

This introduces a second running service with its own hosting resource usage.
The root Railway configuration continues to start `python bot.py`.

## Verification and troubleshooting

Run `python -m unittest discover -s tests -v` for offline command/queue tests.
For a live smoke test, join voice, play one song, add a two-song playlist, skip,
pause/resume, enable radio, and let the queue finish. Confirm a listener in a
different channel cannot stop playback. Finally, run `!stop` and test `!randomquote`.
Live audio requires a Discord token and a running Lavalink instance; offline
tests do not verify provider availability, recommendation quality, or voice transport.

If YouTube fails, inspect the Lavalink logs and the YouTube plugin's documentation
for current provider requirements; try a SoundCloud link to isolate the issue.
Set `MUSIC_SEARCH_SOURCE=scsearch` to default text searches to SoundCloud.
If no recommendations are available, try a different seed or queue a playlist.

Upstream references:
- [Wavelink APIs and autoplay](https://wavelink.readthedocs.io/en/latest/wavelink.html)
- [Lavalink configuration](https://lavalink.dev/configuration/config/file)
- [YouTube source plugin](https://github.com/lavalink-devs/youtube-source)
- [LavaSrc sources and Spotify matching](https://github.com/topi314/LavaSrc)
