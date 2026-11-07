import re

MENTION_RE = re.compile(r"<@!?(\d+)>")

# A "quote mark" is a straight/curly double quote or curly single quote (unambiguous),
# or 2+ repeated straight apostrophes ('''like this'''). A single straight apostrophe is
# deliberately excluded so contractions ("don't", "can't") in message text never trigger
# a false quote boundary.
QUOTE_MARK = r'(?:["“‘’”]|\'{2,4})'

# Attribution follows either a dash ("quote" - Name / -@mention), or - with no dash at all -
# an @mention directly ("quote" <@id>). The no-dash form requires a mention specifically so
# a quote followed by unrelated prose is never mistaken for an attribution.
QUOTE_UNIT_RE = re.compile(
    rf'{QUOTE_MARK}\s*(?P<quote>.+?)\s*{QUOTE_MARK}\s*'
    rf'(?:[-–—]\s*(?P<attr_dash>.*?)|\s*(?P<attr_mention><@!?\d+>.*?))'
    rf'(?={QUOTE_MARK}|$)',
    re.DOTALL,
)


def _parse_attribution(attribution):
    attribution = attribution.strip()
    if not attribution:
        return None, None
    mention = MENTION_RE.search(attribution)
    if mention:
        attribution_id = int(mention.group(1))
        leftover = (attribution[: mention.start()] + " " + attribution[mention.end() :]).strip()
        return (leftover or None), attribution_id
    return attribution.lstrip("@").strip(), None


# For quotes typed without proper quote marks, one per line. Each shape needs a clear
# sign of who said it, so ordinary chat in the channel isn't mistaken for a quote:
#   <@id> quote / @Name: quote        the person first
#   quote <@id> / quote - <@id>       a real mention last
#   quote - Sam / "quote" Sam Lee     a dash or closing mark, then a capitalized name
#                                     of up to 3 words
LEADING_MENTION_RE = re.compile(r"^(?P<who><@!?\d+>)\s*[:,\-–—]?\s*(?P<quote>.+)$", re.DOTALL)
LEADING_AT_NAME_RE = re.compile(r"^@(?P<who>[^\W\d_][\w.']{0,31})\s*[:,\-–—]?\s+(?P<quote>.+)$", re.DOTALL)
TRAILING_MENTION_RE = re.compile(r"^(?P<quote>.+?)\s*[-–—]?\s*(?P<who><@!?\d+>)$", re.DOTALL)
TRAILING_NAME_RE = re.compile(
    r"^(?P<quote>.+?)(?:\s+[-–—]+|\s*[–—]+|[\"”])\s*@?(?P<who>[A-Z][\w.']*(?:\s+[A-Z][\w.']*){0,2})$",
    re.DOTALL,
)
STRAY_MARKS = "\"“”‘’' "


def _parse_unmarked_line(line):
    if line.startswith("!"):
        return None
    for pattern in (LEADING_MENTION_RE, TRAILING_MENTION_RE, LEADING_AT_NAME_RE, TRAILING_NAME_RE):
        match = pattern.match(line)
        if not match:
            continue
        quote = match.group("quote").strip(STRAY_MARKS + ":-–—,")
        if not any(character.isalpha() for character in MENTION_RE.sub("", quote)):
            continue
        name, user_id = _parse_attribution(match.group("who"))
        return quote, name, user_id
    return None


def parse_unmarked_quotes(content):
    """Quotes missing their quote marks, or with the person first. Only used when the
    usual format finds nothing, so a correctly formatted quote reads the same as ever."""
    results = []
    for line in content.strip().splitlines():
        parsed = _parse_unmarked_line(line.strip())
        if parsed:
            results.append(parsed)
    return results


def parse_quotes(content):
    """Extract every "quote" - Name / '''quote''' -@mention / "quote" <@id> unit from
    content - a single message can contain more than one. Falls back to quotes without
    quote marks or with the person first. Returns a list of
    (quote_text, attribution_name_or_None, attribution_user_id_or_None)."""
    if not content:
        return []
    results = _parse_marked_quotes(content)
    return results or parse_unmarked_quotes(content)


def _parse_marked_quotes(content):
    results = []
    for match in QUOTE_UNIT_RE.finditer(content.strip()):
        quote = match.group("quote").strip()
        attribution = match.group("attr_dash")
        if attribution is None:
            attribution = match.group("attr_mention")
        if not quote or not attribution or not attribution.strip():
            continue
        name, user_id = _parse_attribution(attribution)
        if name is None and user_id is None:
            continue
        results.append((quote, name, user_id))
    return results


def parse_quote(content):
    """Backward-compatible single-quote accessor - returns the first match or None."""
    quotes = parse_quotes(content)
    return quotes[0] if quotes else None


_LOOSE_LINE_RE = re.compile(r'^(?P<quote>.+?)\s*[-–—]\s*(?P<attribution>.+)$', re.DOTALL)


def parse_quotes_loose(content):
    """Fallback for messages with no quote marks at all: matches '<text> - <attribution>'
    per line/paragraph. Deliberately NOT used for passive channel scanning - "some
    sentence - a name" is a common shape for ordinary chat too, so applying this
    automatically would false-positive constantly. Only safe for explicit single-message
    commands where a human already picked the message."""
    if not content:
        return []
    results = []
    for para in re.split(r"\n\s*\n|\n", content.strip()):
        para = para.strip()
        if not para:
            continue
        match = _LOOSE_LINE_RE.match(para)
        if not match:
            continue
        quote = match.group("quote").strip().strip("\"“”'")
        attribution = match.group("attribution").strip()
        if not quote or not attribution:
            continue
        name, user_id = _parse_attribution(attribution)
        if name is None and user_id is None:
            continue
        results.append((quote, name, user_id))
    return results
