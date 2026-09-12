"""Small authenticated web dashboard for live Discord music players."""
import hmac
import os

from aiohttp import web
import wavelink

from music_selection import normalize_query, select_tracks
from spotify_resolver import parse_spotify_url


PAGE = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Quote Bot Music</title><style>
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#090b10;color:#f5f7fb}
body{max-width:920px;margin:auto;padding:32px 18px}h1{font-size:30px;margin:0 0 6px}.muted{color:#99a3b4}
.card{background:#141822;border:1px solid #252b39;border-radius:16px;padding:20px;margin:18px 0;box-shadow:0 12px 35px #0005}
.now{font-size:20px;font-weight:700;margin:10px 0}.row{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
button,input{border:1px solid #354056;border-radius:9px;background:#202737;color:white;padding:10px 14px;font:inherit}
button{cursor:pointer}button:hover{background:#2d3850}.danger{border-color:#7d3440}ol{padding-left:25px}li{padding:5px}
.empty{text-align:center;padding:42px}.pill{font-size:12px;background:#243149;padding:4px 8px;border-radius:99px}
.search{display:flex;gap:9px;margin:15px 0}.search input{flex:1;min-width:180px}.status{min-height:22px;margin:8px 0;color:#9cd3ff}
</style></head><body><h1>Quote Bot Music</h1><div class="muted">Live players and queues</div><main id="app"></main>
<script>
const token=location.pathname.split('/').filter(Boolean).pop();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function act(guild,action,value){let r=await fetch(`/api/${token}/control`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({guild,action,value})});let body=await r.text(),d;try{d=JSON.parse(body)}catch{d={error:body||'Request failed'}}let s=document.querySelector(`#s${guild}`);if(s)s.textContent=d.message||d.error||'';if(r.ok)setTimeout(refresh,2500)}
function add(guild){let input=document.querySelector(`#q${guild}`),query=input.value.trim();if(!query)return;act(guild,'play',query);input.value=''}
function card(p){return `<section class=card><div class=row><h2>${esc(p.guild)}</h2><span class=pill>${p.connected?'Connected':'Idle'}</span></div>
<div class=muted>Now playing</div><div class=now>${p.current?esc(p.current.title)+' · '+esc(p.current.author):'Nothing playing'}</div>
<div class=search><input id="q${p.guild_id}" placeholder="Song name, YouTube link, or Spotify link" onkeydown="if(event.key==='Enter')add('${p.guild_id}')"><button onclick="add('${p.guild_id}')">Search & add</button></div><div class=status id="s${p.guild_id}"></div>
<div class=row><button onclick="act('${p.guild_id}','pause')">Pause</button><button onclick="act('${p.guild_id}','resume')">Resume</button>
<button onclick="act('${p.guild_id}','skip')">Skip</button><button onclick="act('${p.guild_id}','shuffle')">Shuffle</button>
<button onclick="act('${p.guild_id}','clear')">Clear queue</button><button class=danger onclick="act('${p.guild_id}','stop')">Stop</button>
<input id="v${p.guild_id}" type=number min=0 max=100 value="${p.volume}" style="width:70px"><button onclick="act('${p.guild_id}','volume',document.querySelector('#v${p.guild_id}').value)">Volume</button></div>
<h3>Queue <span class=muted>(${p.queue.length})</span></h3><ol>${p.queue.slice(0,25).map(t=>`<li>${esc(t.title)} <span class=muted>· ${esc(t.author)}</span></li>`).join('')}</ol></section>`}
async function refresh(){try{let r=await fetch(`/api/${token}/state`);if(!r.ok)throw 0;let d=await r.json();app.innerHTML=d.players.length?d.players.map(card).join(''):'<div class="card empty">No active music player. Start music in Discord first.</div>'}catch{app.innerHTML='<div class="card empty">Dashboard unavailable.</div>'}}
refresh();setInterval(refresh,4000);
</script></body></html>'''


def track_data(track):
    return {"title": track.title, "author": track.author, "uri": track.uri}


class Dashboard:
    def __init__(self, bot):
        self.bot = bot
        self.token = os.getenv("DASHBOARD_TOKEN", "")
        self.runner = None

    def allowed(self, request):
        return bool(self.token and hmac.compare_digest(request.match_info.get("token", ""), self.token))

    async def page(self, request):
        if not self.allowed(request):
            raise web.HTTPNotFound()
        return web.Response(text=PAGE, content_type="text/html")

    async def state(self, request):
        if not self.allowed(request):
            raise web.HTTPNotFound()
        players = []
        for voice in self.bot.voice_clients:
            if not isinstance(voice, wavelink.Player):
                continue
            players.append({
                "guild": voice.guild.name,
                "guild_id": str(voice.guild.id),
                "connected": voice.connected,
                "volume": voice.volume,
                "current": track_data(voice.current) if voice.current else None,
                "queue": [track_data(track) for track in list(voice.queue)],
            })
        return web.json_response({"players": players})

    async def control(self, request):
        if not self.allowed(request):
            raise web.HTTPNotFound()
        data = await request.json()
        player = next((p for p in self.bot.voice_clients if str(p.guild.id) == str(data.get("guild"))), None)
        if not isinstance(player, wavelink.Player):
            raise web.HTTPNotFound(text="Player not found")
        action = data.get("action")
        message = "Done."
        if action == "play":
            message = await self.add_tracks(player, data.get("value", ""))
        elif action == "pause":
            await player.pause(True)
        elif action == "resume":
            await player.pause(False)
        elif action == "skip":
            await player.skip(force=True)
        elif action == "shuffle":
            player.queue.shuffle()
        elif action == "clear":
            player.queue.clear()
            player.auto_queue.clear()
            player.soundcloud_radio = False
            player.autoplay = wavelink.AutoPlayMode.partial
        elif action == "stop":
            await player.disconnect()
        elif action == "volume":
            await player.set_volume(max(0, min(100, int(data.get("value", 50)))))
        else:
            raise web.HTTPBadRequest(text="Unknown action")
        return web.json_response({"ok": True, "message": message})

    async def add_tracks(self, player, raw_query):
        query = normalize_query(str(raw_query))
        if not query:
            raise web.HTTPBadRequest(text="Enter a song name or link.")
        music = self.bot.get_cog("Music")
        if music is None:
            raise web.HTTPServiceUnavailable(text="Music is still starting.")
        async with music.locks[player.guild.id]:
            try:
                spotify_link = bool(parse_spotify_url(query))
                if spotify_link:
                    tracks = await music.spotify_tracks(query)
                else:
                    tracks = await wavelink.Playable.search(
                        query, source=os.getenv("MUSIC_SEARCH_SOURCE", "scsearch")
                    )
                    if not query.startswith(("https://", "http://")) and not isinstance(tracks, wavelink.Playlist):
                        tracks = select_tracks(tracks, query)
            except Exception as error:
                raise web.HTTPBadGateway(text=f"Could not load that song or link: {type(error).__name__}") from error
            if not tracks:
                raise web.HTTPNotFound(text="No matching tracks found.")
            selected = tracks.tracks if isinstance(tracks, wavelink.Playlist) else (tracks if spotify_link else tracks[:1])
            room = max(0, 200 - len(player.queue))
            added = selected[:room]
            if not added:
                raise web.HTTPConflict(text="The queue is full.")
            player.queue.put(added)
            if player.current is None:
                await player.play(player.queue.get())
            return f"Added {len(added)} song(s): {added[0].title}"

    async def start(self):
        if not self.token:
            return
        app = web.Application(client_max_size=16_384)
        app.router.add_get("/{token}", self.page)
        app.router.add_get("/api/{token}/state", self.state)
        app.router.add_post("/api/{token}/control", self.control)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, "0.0.0.0", int(os.getenv("PORT", "8080"))).start()

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
