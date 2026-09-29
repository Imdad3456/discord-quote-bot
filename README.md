# Discord quote and music bot

The existing quote commands, quote cards, and daily quotes remain available.
Music uses a separate Lavalink v4 audio service and Wavelink for Discord control.
Text searches default to SoundCloud because YouTube can require login from hosted
servers. Radio picks songs from Deezer's public recommendations (no API key):
`!radio drake` plays Drake mixed with similar artists, `!radio sza snooze` plays
songs like that track, and `!radio sad songs` uses a curated mood playlist. As it
plays, radio alternates between songs like the last track and songs like the
original seed, never repeats a song (even a different upload), spaces out repeat
artists, skips slowed/sped/cover versions, and finds the next song while the
current one plays. If Deezer is unreachable it falls back to searching the seed. Playback errors stop the session with
one notice, rather than cycling through failing recommendations.

`!stations` lists curated stations. `!radio pop`, `!radio white girl pop`,
`!radio chill jazz`, and `!radio 2015 hits` select known songs instead of matching
the station words against a song title. `!play popular songs` and
`!play 2015 most popular` also start those stations. Starting a new station
replaces the current song while preserving songs explicitly queued with `!play`.
Curated station songs play first; after that the station continues from a
matching Deezer mood playlist instead of stopping.
Search selection excludes previews, snippets, short samples, unsolicited remixes,
and long compilations. Exact links are not subject to the search duration filter.

### Provider authentication

The live server returned `This video requires login` for the supplied YouTube
link and `Failed to retrieve secret from Spotify` for the supplied Spotify playlist.
These are upstream restrictions, not a successful playback test or a disconnected node.
Spotify playlist access uses the account authorization helper in this repository.
Run `python spotify_authorize.py`, approve access in the browser, and store the
result only in the bot service as `SPOTIFY_REFRESH_TOKEN`. Set that service's
`SPOTIFY_CLIENT_ID` to the application client ID. The bot reads Spotify metadata
and finds playable SoundCloud matches; it never streams audio from Spotify.

Authenticated YouTube support is prepared but disabled. Set
`YOUTUBE_OAUTH_ENABLED=true` on Lavalink to start the plugin's device flow. After
authorization, save the logged refresh token as `YOUTUBE_REFRESH_TOKEN`; future
deploys use it automatically. Only the user should complete Google's consent flow.
Follow the upstream YouTube plugin's OAuth guide;
the maintainers warn that authenticated automation can risk the Google account,
and recommend against using a primary account. Authentication does not guarantee
every video is playable. Do not commit credentials to this repository.
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
a seed to the queue; it does not interrupt the current song. `!queue` shows what
radio is based on. Radio is related-track autoplay, not personalized per listener.

## Hosting on a Steam Deck

The bot and its Lavalink music server run together on the Deck, with no cloud host.

1. In Desktop Mode, turn off sleep: Settings → Power → set both "suspend" options to Never.
2. Open Konsole and run:
   ```
   git clone https://github.com/Imdad3456/discord-quote-bot ~/discord-quote-bot
   cd ~/discord-quote-bot
   ./deploy/steamdeck/install.sh
   ```
   The first run creates `.env`. Fill it in (no quotes around values), then run the script again.
3. Copy `quotes.json`, `names.json` and `nicknames.json` into `~/discord-quote-bot`.
4. For the web dashboard, set `DASHBOARD_PUBLIC_URL=http://<deck address>:8080` in `.env`.
   With Tailscale, use the Deck's Tailscale name so it works away from home.

Both services start at boot and restart if they crash.
`journalctl --user -u quotebot -f` shows live logs. After pushing new code to
GitHub, run `./deploy/steamdeck/update.sh` on the Deck.

## Web dashboard

Set a long random `DASHBOARD_TOKEN` on the bot service and expose its `PORT` with
a Railway public domain. Open `https://your-domain/<DASHBOARD_TOKEN>` to see live
players and queues and control pause, resume, skip, shuffle, clear, stop, and volume.
Keep the complete dashboard URL private because the token grants music control.
Server managers can use `!dashboard` to receive the private link by DM. Railway
provides `RAILWAY_PUBLIC_DOMAIN` automatically; on another host, set
`DASHBOARD_PUBLIC_URL` to the dashboard's public origin.

## Supported sources

The included configuration enables YouTube/YouTube Music, SoundCloud, Bandcamp,
Twitch, Vimeo, and Spotify metadata through LavaSrc. Source availability depends
on the hosting IP, region, provider restrictions, and upstream plugin changes.
No bot can promise every link will work.

Spotify tracks, albums, and playlists are matched to audio on SoundCloud, rather
than streamed from Spotify. Matches may differ or fail. Account access requires
`SPOTIFY_CLIENT_ID` and `SPOTIFY_REFRESH_TOKEN` on the bot service. Other services
require additional plugins/configuration.
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
For Spotify links, create an application at <https://developer.spotify.com/dashboard>,
add `http://127.0.0.1:8888/callback` as a redirect URI, run
`python spotify_authorize.py`, and set the resulting `SPOTIFY_CLIENT_ID` and
`SPOTIFY_REFRESH_TOKEN` values in the bot environment.
Never commit `.env` or paste the Discord token into chat.

## Railway setup

Keep the current Python bot service and quote-data volume. Add a second service
from this repository for Lavalink:

1. Set its Root Directory to `/deploy/lavalink`. Railway should detect the
   Dockerfile there. Leave the custom start command empty so the image starts Lavalink.
2. Set `LAVALINK_PASSWORD` on the new service.
3. Enable Railway private networking for the services. Set the bot service's
   `LAVALINK_URI` to `http://<lavalink-private-hostname>:2333`, using the hostname
   shown for your service, and set the same `LAVALINK_PASSWORD` on the bot.
4. For Spotify links, add `SPOTIFY_CLIENT_ID` and `SPOTIFY_REFRESH_TOKEN` to the
   Python bot service, then deploy both services. Check Lavalink logs for startup and plugin loading, and
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
for current provider requirements. The default `MUSIC_SEARCH_SOURCE=ytsearch` is
intentional: SoundCloud search results can expose streams that return 404 at play time.
Set `MUSIC_SEARCH_SOURCE=scsearch` only when SoundCloud playback has been verified.
If no recommendations are available, try a different seed or queue a playlist.

Upstream references:
- [Wavelink APIs and autoplay](https://wavelink.readthedocs.io/en/latest/wavelink.html)
- [Lavalink configuration](https://lavalink.dev/configuration/config/file)
- [YouTube source plugin](https://github.com/lavalink-devs/youtube-source)
- [LavaSrc sources and Spotify matching](https://github.com/topi314/LavaSrc)


## Automatic GitHub deployment on the existing Steam Deck server

The Deck checks the public `master` branch every two minutes. From your PC:

```sh
cd ~/Projects/discord-quote-bot
git add <changed-files>
git commit -m "Describe the change"
git push origin master
```

No inbound port or GitHub SSH secret is required. Only pushed commits on `master`
are deployed. A push triggers a build and offline tests on the next check, then a
brief restart of the bot and Lavalink; active music queues are lost on restart.
A failed build/test leaves the live bot running. A failed startup restores the
previous images. The updater verifies the authenticated dashboard has a Discord
guild and Lavalink responds; it cannot verify audible playback.

Quotes, names, secrets, and daily backups remain outside the checkout under
`~/server/discord-quote-bot`. A data backup runs before each rollout. Runtime
rollback restores images, not data: schema changes need a compatible migration.
This deployment expects a configured dashboard token and membership in a Discord
server. Candidate containers are tested without network access or production secrets.

On the Deck, `deploy/steamdeck/enable-autoupdate.sh` installs the updater for the
existing `discord-quote-bot` and `discord-lavalink` Podman services. The older
`install.sh` is for a fresh virtualenv installation and refuses to create a
second bot alongside these services. Updater code itself is installed separately:
rerun `enable-autoupdate.sh` on the Deck to upgrade it after reviewing changes.

```sh
systemctl --user list-timers discord-bot-update.timer
journalctl --user -u discord-bot-update -n 60 --no-pager
cat ~/server/discord-quote-bot/deploy-state.json
systemctl --user start discord-bot-update.service  # check now
systemctl --user stop discord-bot-update.timer    # pause polling
```

A failed revision is not repeatedly redeployed. Push a fix, or explicitly retry:
`python3 ~/server/discord-quote-bot/deploy/autoupdate.py --retry`.
The previous working images remain tagged `:previous`; build images are retained
for diagnosis and can be pruned during maintenance. Keep the Deck powered,
connected, and awake. Updates resume automatically when it is back online.
