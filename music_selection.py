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
    "hip hop": [
        "Kendrick Lamar HUMBLE", "Drake God's Plan", "Travis Scott SICKO MODE",
        "J Cole No Role Modelz", "Kanye West Stronger", "Outkast Ms Jackson",
        "50 Cent In Da Club", "Lil Uzi Vert XO TOUR Llif3",
    ],
    "r&b": [
        "SZA Snooze", "Frank Ocean Thinkin Bout You", "The Weeknd Die For You",
        "Usher U Got It Bad", "Alicia Keys If I Ain't Got You", "Brent Faiyaz Clouded",
        "Daniel Caesar Best Part", "Beyonce Cuff It",
    ],
    "rock classics": [
        "Queen Don't Stop Me Now", "Fleetwood Mac Dreams", "ACDC Back In Black",
        "Bon Jovi Livin On A Prayer", "Guns N Roses Sweet Child O Mine",
        "Journey Don't Stop Believin", "The Eagles Hotel California", "Nirvana Come As You Are",
    ],
    "indie": [
        "Arctic Monkeys Do I Wanna Know", "Tame Impala The Less I Know The Better",
        "The Strokes Last Nite", "MGMT Electric Feel", "Cage The Elephant Cigarette Daydreams",
        "The 1975 Somebody Else", "Vampire Weekend A Punk", "Beach House Space Song",
    ],
    "electronic": [
        "Daft Punk One More Time", "Avicii Levels", "Calvin Harris Feel So Close",
        "Disclosure Latch", "Zedd Clarity", "Swedish House Mafia Don't You Worry Child",
        "David Guetta Titanium", "Martin Garrix Animals",
    ],
    "afrobeats": [
        "Burna Boy Last Last", "Wizkid Essence", "Rema Calm Down", "Tems Free Mind",
        "Davido Fall", "Ayra Starr Rush", "Fireboy DML Peru", "Asake Lonely At The Top",
    ],
    "latin": [
        "Bad Bunny Tití Me Preguntó", "Karol G Provenza", "Daddy Yankee Gasolina",
        "J Balvin Mi Gente", "Shakira Hips Don't Lie", "Luis Fonsi Despacito",
        "Rosalia Despecha", "Enrique Iglesias Bailando",
    ],
    "country": [
        "Chris Stapleton Tennessee Whiskey", "Dolly Parton Jolene", "Luke Combs Beautiful Crazy",
        "Shania Twain Man I Feel Like A Woman", "Morgan Wallen Last Night",
        "Zach Bryan Something in the Orange", "Johnny Cash Ring of Fire", "Kacey Musgraves Slow Burn",
    ],
    "reggae": [
        "Bob Marley Three Little Birds", "Peter Tosh Legalize It", "UB40 Red Red Wine",
        "Jimmy Cliff The Harder They Come", "Sean Paul Temperature", "Shaggy Angel",
        "Damian Marley Welcome To Jamrock", "Toots and the Maytals Pressure Drop",
    ],
    "lo-fi": [
        "idealism both of us", "jinsang affection", "potsu just friends",
        "Kupla Kingdom in Blue", "SwuM This Again", "L'indécis Soulful",
        "Nymano Solitude", "Tomppabeats Monday Loop",
    ],
    "80s hits": [
        "A Ha Take On Me", "Michael Jackson Billie Jean", "Whitney Houston I Wanna Dance With Somebody",
        "Toto Africa", "Prince Purple Rain", "Cyndi Lauper Girls Just Want to Have Fun",
        "George Michael Faith", "Bonnie Tyler Total Eclipse of the Heart",
    ],
    "90s hits": [
        "Backstreet Boys I Want It That Way", "TLC No Scrubs", "Britney Spears Baby One More Time",
        "Spice Girls Wannabe", "Oasis Wonderwall", "Natalie Imbruglia Torn",
        "MC Hammer U Can't Touch This", "No Doubt Don't Speak",
    ],
    "2000s throwbacks": [
        "Beyonce Crazy In Love", "Outkast Hey Ya", "Rihanna Umbrella", "Nelly Hot In Herre",
        "Kelly Clarkson Since U Been Gone", "Usher Yeah", "The Killers Mr Brightside",
        "Gwen Stefani Hollaback Girl",
    ],
    "workout": [
        "Eminem Till I Collapse", "Kanye West Power", "Dua Lipa Physical",
        "Fort Minor Remember The Name", "Survivor Eye of the Tiger", "Macklemore Can't Hold Us",
        "DMX X Gon Give It To Ya", "The Prodigy Breathe",
    ],
    "party": [
        "Pitbull Give Me Everything", "LMFAO Party Rock Anthem", "Black Eyed Peas I Gotta Feeling",
        "Flo Rida Low", "Kesha Tik Tok", "Taio Cruz Dynamite", "Sean Paul Get Busy",
        "David Guetta Memories",
    ],
}
ALIASES = {"white girl pop": "pop", "popular songs": "pop", "pop hits": "pop",
           "2015 most popular": "2015 hits", "2015 popular songs": "2015 hits",
           "2015": "2015 hits", "jazz": "chill jazz", "smooth jazz": "chill jazz",
           "rap": "hip hop", "hip-hop": "hip hop", "edm": "electronic",
           "classic rock": "rock classics", "2000s": "2000s throwbacks",
           "80s": "80s hits", "90s": "90s hits", "gym": "workout"}


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


def select_tracks(tracks, query, *, strict=False, expected_length=None):
    wanted = tokens(query)
    ranked = []
    for track in tracks:
        words = tokens(track.title)
        if words & {"preview", "snippet", "teaser", "sample"}:
            continue
        if words & ({"remix", "mix", "cover", "karaoke", "sped", "slowed", "medley", "mashup",
                    "edit", "version", "bootleg", "rework", "tribute", "instrumental"} - wanted):
            continue
        if strict and "/" in track.title and "/" not in query:
            continue
        if not track.is_stream and not 90000 <= track.length <= 900000:
            continue
        if strict and expected_length and not track.is_stream:
            tolerance = max(12000, expected_length * 0.08)
            if abs(track.length - expected_length) > tolerance:
                continue
        matched = len(wanted & tokens(track.title + " " + track.author)) / max(1, len(wanted))
        if strict and matched < 0.65:
            continue
        ranked.append((matched, track))
    return [t for _, t in sorted(ranked, key=lambda pair: pair[0], reverse=True)]
