"""Small authenticated web dashboard for live Discord music players."""
import hmac
import os
import random
from collections import deque

from aiohttp import web
import discord
import wavelink

from music_selection import STATIONS, normalize_query, select_tracks, station_name
from spotify_resolver import parse_spotify_url


PAGE = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Quote Bot Music</title><style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#08090c;color:#f7f7fa;--panel:#121318;--soft:#1b1d24;--line:#292c36;--muted:#969baa;--accent:#8b5cf6;--pink:#ec4899}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#281a45 0,transparent 32%),#08090c;min-height:100vh}button,input,select{font:inherit;color:inherit}
header{height:72px;border-bottom:1px solid #ffffff12;display:flex;align-items:center;justify-content:space-between;padding:0 max(22px,calc((100vw - 1240px)/2));background:#0b0c10cc;backdrop-filter:blur(18px);position:sticky;top:0;z-index:5}
.brand{display:flex;gap:12px;align-items:center;font-weight:800;font-size:19px}.logo{width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--pink));display:grid;place-items:center;box-shadow:0 8px 28px #8b5cf655}.live{font-size:12px;color:#a7f3d0;background:#12352b;border:1px solid #23634f;padding:6px 10px;border-radius:99px}
main{max-width:1240px;margin:auto;padding:32px 22px 70px}.server{margin-bottom:36px}.server-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.server h1{font-size:25px;margin:0}.sub,.muted{color:var(--muted)}
.layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(310px,.8fr);gap:18px}.panel{background:linear-gradient(145deg,#17181e,#111217);border:1px solid var(--line);border-radius:22px;padding:22px;box-shadow:0 22px 60px #0005}.wide{grid-column:1/-1}
.search{display:flex;gap:10px}.search input{flex:1;min-width:100px}.field,input,select{background:#0d0e13;border:1px solid #30333d;border-radius:12px;padding:12px 14px;outline:none}input:focus,select:focus{border-color:#8b5cf6;box-shadow:0 0 0 3px #8b5cf622}
button{border:1px solid #343742;background:#20222a;border-radius:12px;padding:11px 15px;cursor:pointer;font-weight:650;transition:.16s}button:hover{transform:translateY(-1px);background:#2a2d37}.primary{border:0;background:linear-gradient(135deg,var(--accent),#6d45db);box-shadow:0 8px 24px #8b5cf633}.danger{color:#fca5a5}.label{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:750;margin-bottom:11px}
.playing{display:grid;grid-template-columns:170px 1fr;gap:22px;align-items:center}.art{width:170px;aspect-ratio:1;border-radius:18px;object-fit:cover;background:linear-gradient(145deg,#42256f,#13151c);box-shadow:0 20px 45px #0008}.song{font-size:25px;font-weight:850;margin:5px 0}.artist{color:var(--muted);font-size:16px}.progress{height:5px;background:#2c2f38;border-radius:9px;overflow:hidden;margin:22px 0 9px}.progress i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--pink))}.times{display:flex;justify-content:space-between;font-size:12px;color:var(--muted)}
.controls{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:17px}.round{width:45px;height:45px;border-radius:50%;padding:0;font-size:17px}.play{width:52px;height:52px;background:white;color:#111;border:0}.volume{display:flex;align-items:center;gap:8px;margin-left:auto}.volume input{width:72px}
.stations{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.station{min-height:115px;text-align:left;padding:15px;position:relative;overflow:hidden}.station b{display:block;font-size:16px;margin-top:27px}.station span{font-size:24px}.station.active{border-color:#a78bfa;background:#2a2040}.station:after{content:'▶';position:absolute;right:13px;top:13px;opacity:.55}
.queue-head{display:flex;justify-content:space-between;align-items:center}.queue{display:grid;gap:5px;margin-top:12px}.track{display:grid;grid-template-columns:34px 1fr auto;align-items:center;gap:12px;padding:10px;border-radius:12px}.track:hover{background:#ffffff08}.track b{font-size:14px}.track small{display:block;color:var(--muted);margin-top:3px}.num{color:#777d8b;text-align:center}.empty{color:var(--muted);text-align:center;padding:34px}.status{min-height:22px;color:#c4b5fd;margin-top:10px;font-size:14px}.connect{display:flex;gap:10px;align-items:center}.radio-state{font-size:12px;background:#2a2040;color:#d8c8ff;padding:6px 10px;border-radius:99px}
@media(max-width:800px){.layout{grid-template-columns:1fr}.playing{grid-template-columns:105px 1fr}.art{width:105px}.song{font-size:20px}.stations{grid-template-columns:1fr}.search{flex-wrap:wrap}.search input{width:100%;flex-basis:100%}.volume{margin-left:0}header{padding:0 18px}}
</style></head><body><header><div class=brand><div class=logo>♫</div>Quote Bot Music</div><div class=live>● Bot online</div></header><main id="app"><div class="panel empty">Loading your servers…</div></main>
<script>
const token=location.pathname.split('/').filter(Boolean).pop(),icons={'chill jazz':'☕','pop':'✨','2015 hits':'📻'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=n=>{n=Math.max(0,Math.floor((n||0)/1000));return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`};
async function act(guild,action,value,channel){let s=document.querySelector(`#s${guild}`);if(s)s.textContent='Working…';let r=await fetch(`/api/${token}/control`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({guild,action,value,channel})}),body=await r.text(),d;try{d=JSON.parse(body)}catch{d={error:body||'Request failed'}}if(s)s.textContent=d.message||d.error||'';if(r.ok)setTimeout(()=>refresh(true),1200)}
function channel(g){return document.querySelector(`#c${g}`)?.value}function add(g){let q=document.querySelector(`#q${g}`),v=q.value.trim();if(v){act(g,'play',v,channel(g));q.value=''}}function radio(g,s){act(g,'radio',s,channel(g))}
function station(s,p){return `<button class="station ${p.radio===s?'active':''}" onclick="radio('${p.guild_id}','${s}')"><span>${icons[s]||'♫'}</span><b>${esc(s)}</b><small class=muted>${p.radio===s?'On air':'Start station'}</small></button>`}
function card(p){let c=p.current,percent=c&&c.length?Math.min(100,p.position/c.length*100):0,connect=p.connected?'':`<div class=connect><span class=muted>Play in</span><select id="c${p.guild_id}">${p.channels.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></div>`;return `<section class=server><div class=server-head><div><h1>${esc(p.guild)}</h1><div class=sub>${p.connected?'Connected to voice':'Choose a voice channel to start'}</div></div>${p.radio?`<span class=radio-state>● ${esc(p.radio)} radio</span>`:''}</div>${connect}<div class="panel wide" style="margin-top:16px"><div class=label>Search & play</div><div class=search><input id="q${p.guild_id}" placeholder="Search a song or paste a YouTube / Spotify link" onkeydown="if(event.key==='Enter')add('${p.guild_id}')"><button class=primary onclick="add('${p.guild_id}')">Search & add</button></div><div class=status id="s${p.guild_id}"></div></div><div class=layout><div class=panel><div class=label>Now playing</div><div class=playing><img class=art src="${c&&c.artwork?esc(c.artwork):''}" alt=""><div><div class=song>${c?esc(c.title):'Nothing playing'}</div><div class=artist>${c?esc(c.author):'Pick a song or station to begin'}</div><div class=progress><i style="width:${percent}%"></i></div><div class=times><span>${time(p.position)}</span><span>${c?time(c.length):'0:00'}</span></div><div class=controls><button onclick="act('${p.guild_id}','shuffle')">⇄</button><button class=round onclick="act('${p.guild_id}','pause')">Ⅱ</button><button class="round play" onclick="act('${p.guild_id}','resume')">▶</button><button class=round onclick="act('${p.guild_id}','skip')">▶|</button><button class=danger onclick="act('${p.guild_id}','stop')">Stop</button><div class=volume>🔊 <input id="v${p.guild_id}" type=number min=0 max=100 value="${p.volume}"><button onclick="act('${p.guild_id}','volume',document.querySelector('#v${p.guild_id}').value)">Set</button></div></div></div></div></div><div class=panel><div class=queue-head><div class=label>Radio stations</div>${p.radio?`<button onclick="act('${p.guild_id}','radio_off')">Turn off</button>`:''}</div><div class=stations>${p.stations.map(s=>station(s,p)).join('')}</div></div><div class="panel wide"><div class=queue-head><div><div class=label>Up next</div><b>${p.queue.length} song${p.queue.length===1?'':'s'} queued</b></div><button onclick="act('${p.guild_id}','clear')">Clear queue</button></div><div class=queue>${p.queue.length?p.queue.slice(0,25).map((t,i)=>`<div class=track><span class=num>${i+1}</span><div><b>${esc(t.title)}</b><small>${esc(t.author)}</small></div><small>${time(t.length)}</small></div>`).join(''):'<div class=empty>Your queue is empty.</div>'}</div></div></div></section>`}
async function refresh(force=false){if(!force&&['INPUT','SELECT'].includes(document.activeElement?.tagName))return;try{let r=await fetch(`/api/${token}/state`);if(!r.ok)throw 0;let d=await r.json();app.innerHTML=d.players.length?d.players.map(card).join(''):'<div class="panel empty">The bot is not connected to any Discord servers.</div>'}catch{app.innerHTML='<div class="panel empty">Dashboard unavailable. Try refreshing.</div>'}}
refresh();setInterval(refresh,4000);
</script></body></html>'''


def track_data(track):
    return {
        "title": track.title,
        "author": track.author,
        "uri": track.uri,
        "artwork": getattr(track, "artwork", None),
        "length": getattr(track, "length", 0),
    }


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
        for guild in self.bot.guilds:
            voice = next((p for p in self.bot.voice_clients if p.guild.id == guild.id), None)
            player = voice if isinstance(voice, wavelink.Player) else None
            players.append({
                "guild": guild.name,
                "guild_id": str(guild.id),
                "connected": bool(player and player.connected),
                "volume": player.volume if player else 50,
                "position": player.position if player else 0,
                "current": track_data(player.current) if player and player.current else None,
                "queue": [track_data(track) for track in list(player.queue)] if player else [],
                "channels": [{"id": str(channel.id), "name": channel.name} for channel in guild.voice_channels],
                "stations": list(STATIONS),
                "radio": getattr(player, "station_name", None) if player and getattr(player, "soundcloud_radio", False) else None,
            })
        return web.json_response({"players": players})

    async def control(self, request):
        if not self.allowed(request):
            raise web.HTTPNotFound()
        data = await request.json()
        guild = self.bot.get_guild(int(data.get("guild", 0)))
        if guild is None:
            raise web.HTTPNotFound(text="Server not found")
        player = next((p for p in self.bot.voice_clients if p.guild.id == guild.id), None)
        action = data.get("action")
        message = "Done."
        if action in ("play", "radio"):
            if not isinstance(player, wavelink.Player):
                channel = guild.get_channel(int(data.get("channel") or 0))
                if not isinstance(channel, discord.VoiceChannel):
                    raise web.HTTPBadRequest(text="Choose a voice channel first.")
                permissions = channel.permissions_for(guild.me)
                if not permissions.connect or not permissions.speak:
                    raise web.HTTPForbidden(text="The bot needs Connect and Speak permissions there.")
                player = await channel.connect(cls=wavelink.Player, self_deaf=True)
                player.autoplay = wavelink.AutoPlayMode.partial
            message = await (self.start_radio(player, data.get("value", "")) if action == "radio" else self.add_tracks(player, data.get("value", "")))
        elif not isinstance(player, wavelink.Player):
            raise web.HTTPNotFound(text="Start a song first.")
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
        elif action == "radio_off":
            player.soundcloud_radio = False
            player.station_name = None
            player.auto_queue.clear()
            player.autoplay = wavelink.AutoPlayMode.partial
            message = "Radio is off."
        elif action == "stop":
            await player.disconnect()
        elif action == "volume":
            await player.set_volume(max(0, min(100, int(data.get("value", 50)))))
        else:
            raise web.HTTPBadRequest(text="Unknown action")
        return web.json_response({"ok": True, "message": message})

    async def start_radio(self, player, raw_station):
        station = station_name(str(raw_station))
        if station is None:
            raise web.HTTPBadRequest(text="Choose a valid radio station.")
        music = self.bot.get_cog("Music")
        if music is None:
            raise web.HTTPServiceUnavailable(text="Music is still starting.")
        async with music.locks[player.guild.id]:
            seeds = deque(STATIONS[station].copy())
            random.shuffle(seeds)
            tracks = await music.station_track(seeds, set())
            if not tracks:
                raise web.HTTPBadGateway(text="That station could not find a playable song.")
            track = tracks[0]
            player.music_failures = 0
            player.music_recovering = False
            player.soundcloud_radio = True
            player.station_seeds = seeds
            player.station_name = station
            player.radio_query = station
            player.radio_seen = {track.identifier}
            player.auto_queue.clear()
            player.autoplay = wavelink.AutoPlayMode.disabled
            await player.play(track)
            return f"Radio started: {station} — {track.title}"

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
