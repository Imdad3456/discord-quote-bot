"""Deterministic station intent and track-quality selection (no provider credentials)."""
import html
import re
import unicodedata
from urllib.parse import urlsplit

STATIONS = {
    "chill jazz": [
        "Norah Jones Come Away With Me", "Bill Evans Peace Piece",
        "Chet Baker I Fall In Love Too Easily", "Stan Getz Corcovado",
        "Miles Davis Blue in Green", "Ella Fitzgerald Misty",
        "Diana Krall The Look of Love", "Dave Brubeck Take Five",
        "Vince Guaraldi Cast Your Fate to the Wind", "Oscar Peterson My One and Only Love",
    ],
    "pop": [
        "Dua Lipa Levitating", "Taylor Swift Cruel Summer", "Lady Gaga Bad Romance",
        "Katy Perry Teenage Dream", "Rihanna Only Girl In The World",
        "Ariana Grande Into You", "Carly Rae Jepsen Call Me Maybe",
        "Britney Spears Toxic", "Kesha Tik Tok", "Sabrina Carpenter Espresso",
        "Miley Cyrus Party In The USA", "Chappell Roan Good Luck Babe",
    ],
    "2015 hits": [
        "Mark Ronson Bruno Mars Uptown Funk", "Taylor Swift Blank Space",
        "The Weeknd Can't Feel My Face", "Walk The Moon Shut Up and Dance",
        "Ellie Goulding Love Me Like You Do", "Justin Bieber Sorry",
        "Major Lazer DJ Snake Lean On", "Adele Hello", "OMI Cheerleader",
        "Ed Sheeran Thinking Out Loud", "Maroon 5 Sugar", "Wiz Khalifa See You Again",
    ],
}
ALIASES = {"white girl pop": "pop", "popular songs": "pop", "pop hits": "pop",
           "2015 most popular": "2015 hits", "2015 popular songs": "2015 hits",
           "2015": "2015 hits", "jazz": "chill jazz", "smooth jazz": "chill jazz"}


def normalize_query(value):
    value = html.unescape(value).strip()
    link = re.fullmatch(r"\[[^\]]*\]\((https?://[^\s]+)\)", value)
    if link:
        value = link.group(1)
    value = value.strip("<>").replace(r"\_", "_").replace(r"\&", "&")
    return value


def station_name(query):
    key = " ".join(query.lower().split())
    return key if key in STATIONS else ALIASES.get(key)


def provider(query):
    host = (urlsplit(query).hostname or "").lower()
    for domain, name in [("spotify.com", "Spotify"), ("spotify.link", "Spotify"),
                         ("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
                         ("soundcloud.com", "SoundCloud")]:
        if host == domain or host.endswith("." + domain):
            return name
    return "This source"


def tokens(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return set(re.findall(r"[a-z0-9]+", value.lower())) - {"the", "a", "and", "feat", "ft", "official", "audio", "lyrics"}


def select_tracks(tracks, query, *, strict=False):
    wanted = tokens(query)
    ranked = []
    for track in tracks:
        words = tokens(track.title)
        if words & {"preview", "snippet", "teaser", "sample"}:
            continue
        if words & ({"remix", "mix", "cover", "karaoke", "sped", "slowed"} - wanted):
            continue
        if not track.is_stream and not 90000 <= track.length <= 900000:
            continue
        matched = len(wanted & tokens(track.title + " " + track.author)) / max(1, len(wanted))
        if strict and matched < 0.65:
            continue
        ranked.append((matched, track))
    return [t for _, t in sorted(ranked, key=lambda pair: pair[0], reverse=True)]
