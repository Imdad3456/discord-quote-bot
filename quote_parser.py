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


def parse_quotes(content):
    """Extract every "quote" - Name / '''quote''' -@mention / "quote" <@id> unit from
    content - a single message can contain more than one. Returns a list of
    (quote_text, attribution_name_or_None, attribution_user_id_or_None)."""
    if not content:
        return []
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
