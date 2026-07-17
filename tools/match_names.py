"""Match a previous quote-book's (quote, name) pairs against recorded Discord
quotes and current server nicknames to figure out which Discord user each
real name corresponds to.

Prerequisites:
  1. Run extract_quotebook.py against the old .docx to produce previous_quotebook.json.
  2. Run the bot and use `!sync` (or let it backfill on startup) so ../quotes.json
     is populated with real messages, authors, and author IDs from the channel.
  3. (Recommended) Run `!nicknames` in Discord so ../nicknames.json has each
     author's current server nickname/display name - this fills in people whose
     old quotes no longer exist in the channel, or confirms/conflicts with the
     quote-text match.

Usage: python tools/match_names.py
Writes suggested_names.json and match_report.txt in this folder.
"""
import difflib
import json
import os
import re
import string
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PREVIOUS_BOOK = os.path.join(HERE, "previous_quotebook.json")
QUOTES_FILE = os.path.join(HERE, "..", "quotes.json")
FILTERED_QUOTES_FILE = os.path.join(HERE, "..", "filtered_quotes.json")
NICKNAMES_FILE = os.path.join(HERE, "..", "nicknames.json")
QUOTE_MATCH_THRESHOLD = 0.82
NAME_MATCH_THRESHOLD = 0.6

QUOTE_CHARS = str.maketrans({c: '"' for c in "“”‘’"})


def normalize_quote(text):
    text = text.translate(QUOTE_CHARS)
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_name(text):
    return re.sub(r"[^a-z]", "", text.lower())


def name_similarity(a, b):
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.9
    return difflib.SequenceMatcher(None, na, nb).ratio()


def best_name_match(candidate, name_pool):
    best, best_ratio = None, 0.0
    for name in name_pool:
        ratio = name_similarity(candidate, name)
        if ratio > best_ratio:
            best, best_ratio = name, ratio
    return best, best_ratio


def match_quotes_to_recorded(previous, recorded):
    recorded_norm = [
        {**q, "_norm": normalize_quote(q.get("parsed_quote") or q["content"])}
        for q in recorded
        if q.get("parsed_quote") or q.get("content")
    ]

    votes = defaultdict(Counter)  # quoted_person's author_id -> Counter(name -> count)
    matches = []
    unmatched = []
    no_id_available = []

    for entry in previous:
        target = normalize_quote(entry["quote"])
        if not target:
            continue
        best, best_ratio = None, 0.0
        for q in recorded_norm:
            ratio = difflib.SequenceMatcher(None, target, q["_norm"]).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = q
        if best and best_ratio >= QUOTE_MATCH_THRESHOLD:
            # The quoted person is whoever the message attributes it to (parsed from
            # the "- Name" / "-@mention" in the message text), NOT whoever posted the
            # message in the channel - one person often posts many others' quotes.
            attribution_id = best.get("parsed_attribution_id")
            attribution_name = best.get("parsed_attribution")
            matches.append(
                {
                    "quote": entry["quote"],
                    "attributed_name": entry["name"],
                    "matched_content": best.get("parsed_quote") or best["content"],
                    "matched_attribution_id": attribution_id,
                    "matched_attribution_name": attribution_name,
                    "matched_message_author_id": best["author_id"],
                    "confidence": round(best_ratio, 3),
                }
            )
            if not entry["name"].startswith("@"):
                if attribution_id is not None:
                    votes[str(attribution_id)][entry["name"]] += 1
                else:
                    # Matched the quote text, but the message attributed it with a plain
                    # name/handle (no @mention), so there's no Discord ID to vote for here.
                    no_id_available.append(
                        {"quote": entry["quote"], "attributed_name": entry["name"], "message_attribution": attribution_name}
                    )
        else:
            unmatched.append({"quote": entry["quote"], "attributed_name": entry["name"], "best_ratio": round(best_ratio, 3)})

    return votes, matches, unmatched, no_id_available


def match_nicknames(nicknames, name_pool):
    """For each Discord author_id's current nickname, find the closest old-book name."""
    nickname_matches = {}
    for author_id, info in nicknames.items():
        candidates = [c for c in (info.get("nick"), info.get("display_name"), info.get("username")) if c]
        best_overall, best_ratio_overall, best_candidate = None, 0.0, None
        for candidate in candidates:
            name, ratio = best_name_match(candidate, name_pool)
            if ratio > best_ratio_overall:
                best_overall, best_ratio_overall, best_candidate = name, ratio, candidate
        nickname_matches[author_id] = {
            "raw": info.get("display_name") or info.get("nick") or info.get("username"),
            "matched_name": best_overall if best_ratio_overall >= NAME_MATCH_THRESHOLD else None,
            "confidence": round(best_ratio_overall, 3),
            "source_candidate": best_candidate,
        }
    return nickname_matches


def main():
    if not os.path.exists(PREVIOUS_BOOK):
        raise SystemExit(f"Missing {PREVIOUS_BOOK}. Run extract_quotebook.py first.")
    if not os.path.exists(QUOTES_FILE):
        raise SystemExit(
            f"Missing {QUOTES_FILE}. Run the bot first (it backfills on startup, "
            "or use !sync) so quotes.json has real Discord messages to match against."
        )

    previous = json.load(open(PREVIOUS_BOOK, encoding="utf-8"))
    if os.path.exists(FILTERED_QUOTES_FILE):
        recorded = json.load(open(FILTERED_QUOTES_FILE, encoding="utf-8"))
        print(f"Using filtered_quotes.json ({len(recorded)} formatted quotes) as the match target.")
    else:
        recorded = json.load(open(QUOTES_FILE, encoding="utf-8"))
        print(
            f"filtered_quotes.json not found - matching against all {len(recorded)} raw messages in "
            "quotes.json instead. Run tools/filter_quotes.py first for better accuracy."
        )
    nicknames = json.load(open(NICKNAMES_FILE, encoding="utf-8")) if os.path.exists(NICKNAMES_FILE) else {}

    name_pool = sorted({e["name"] for e in previous if not e["name"].startswith("@")})

    votes, matches, unmatched, no_id_available = match_quotes_to_recorded(previous, recorded)
    nickname_matches = match_nicknames(nicknames, name_pool) if nicknames else {}

    all_author_ids = set(votes) | set(nickname_matches)

    suggested_names = {}
    conflicts = []
    low_confidence = []

    for author_id in all_author_ids:
        quote_name = votes[author_id].most_common(1)[0][0] if author_id in votes else None
        nick_info = nickname_matches.get(author_id, {})
        nick_name = nick_info.get("matched_name")
        raw_nick = nick_info.get("raw")

        if quote_name and nick_name:
            if normalize_name(quote_name) == normalize_name(nick_name):
                suggested_names[author_id] = quote_name
            else:
                conflicts.append(
                    {
                        "author_id": author_id,
                        "quote_text_says": quote_name,
                        "nickname_says": nick_name,
                        "raw_nickname": raw_nick,
                    }
                )
        elif quote_name:
            suggested_names[author_id] = quote_name
        elif nick_name:
            suggested_names[author_id] = nick_name
        elif raw_nick:
            suggested_names[author_id] = raw_nick
            low_confidence.append({"author_id": author_id, "raw_nickname": raw_nick})

    with open(os.path.join(HERE, "suggested_names.json"), "w", encoding="utf-8") as f:
        json.dump(suggested_names, f, indent=2, ensure_ascii=False)

    with open(os.path.join(HERE, "match_report.txt"), "w", encoding="utf-8") as f:
        f.write(f"Matched {len(matches)} / {len(previous)} quotes by text (threshold {QUOTE_MATCH_THRESHOLD}).\n")
        f.write(f"Nicknames loaded for {len(nicknames)} member(s).\n\n")

        f.write("=== Suggested author_id -> name mappings ===\n")
        for author_id, name in suggested_names.items():
            f.write(f"{author_id} -> {name}\n")

        if conflicts:
            f.write("\n=== CONFLICTS: quote text and nickname disagree, review these ===\n")
            for c in conflicts:
                f.write(
                    f"author_id {c['author_id']}: quote text says '{c['quote_text_says']}', "
                    f"nickname is '{c['raw_nickname']}' (closest old-book match: '{c['nickname_says']}')\n"
                )

        if low_confidence:
            f.write("\n=== LOW CONFIDENCE: no quote-text or old-book name match, using raw nickname as-is ===\n")
            for lc in low_confidence:
                f.write(f"author_id {lc['author_id']}: '{lc['raw_nickname']}'\n")

        if no_id_available:
            f.write(
                f"\n=== MATCHED TEXT BUT NO DISCORD ID ({len(no_id_available)}) - message attributed the quote "
                "with a plain name/handle, not an @mention, so there's no ID to map ===\n"
            )
            for n in no_id_available:
                f.write(f"\"{n['quote'][:70]}\" - old book says '{n['attributed_name']}', message says '{n['message_attribution']}'\n")

        f.write(f"\n=== Unmatched quotes ({len(unmatched)}) - not found in quotes.json ===\n")
        for u in unmatched:
            f.write(f"[{u['best_ratio']}] \"{u['quote'][:70]}\" - {u['attributed_name']}\n")

    print(f"Matched {len(matches)} / {len(previous)} quotes by text.")
    print(f"Nicknames loaded for {len(nicknames)} member(s).")
    print(f"Suggested {len(suggested_names)} name mappings -> suggested_names.json")
    if conflicts:
        print(f"WARNING: {len(conflicts)} conflict(s) between quote text and nickname - check match_report.txt")
    if low_confidence:
        print(f"{len(low_confidence)} mapping(s) are low-confidence (raw nickname only) - review before trusting")
    if no_id_available:
        print(f"{len(no_id_available)} quote(s) matched text but had no @mention to get a Discord ID from")
    print(f"{len(unmatched)} quotes from the old book had no good match in quotes.json (see match_report.txt)")


if __name__ == "__main__":
    main()
