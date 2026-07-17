import re

MENTION_RE = re.compile(r"<@!?(\d+)>")

QUOTE_LINE_RE = re.compile(
    r'^[\'"“‘]{1,4}\s*(?P<quote>.+?)\s*[\'"”’]{1,4}\s*[-–—]\s*(?P<attribution>\S.*)$',
    re.DOTALL,
)


def parse_quote(content):
    """If content looks like a formatted quote ("text" - Name / '''text''' -@user),
    return (quote_text, attribution_name_or_None, attribution_user_id_or_None).
    Returns None if content doesn't match the pattern."""
    if not content:
        return None
    match = QUOTE_LINE_RE.match(content.strip())
    if not match:
        return None

    quote = match.group("quote").strip()
    attribution = match.group("attribution").strip()
    if not quote or not attribution:
        return None

    mention = MENTION_RE.search(attribution)
    if mention:
        attribution_id = int(mention.group(1))
        leftover = (attribution[: mention.start()] + " " + attribution[mention.end() :]).strip()
        return quote, leftover or None, attribution_id
    return quote, attribution.lstrip("@").strip(), None
