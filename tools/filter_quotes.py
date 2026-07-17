"""Filter ../quotes.json down to messages that actually look like formatted
quotes ("text" - Name / '''text''' -@user), discarding regular chatter.

Usage: python tools/filter_quotes.py
Writes filtered_quotes.json (in the project root) and prints match stats.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from quote_parser import parse_quotes  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
QUOTES_FILE = os.path.join(HERE, "..", "quotes.json")
OUTPUT_FILE = os.path.join(HERE, "..", "filtered_quotes.json")


def main():
    if not os.path.exists(QUOTES_FILE):
        raise SystemExit(f"Missing {QUOTES_FILE}. Run the bot first so it can backfill quotes.")

    quotes = json.load(open(QUOTES_FILE, encoding="utf-8"))
    matched = []
    for q in quotes:
        for quote_text, attribution_name, attribution_id in parse_quotes(q.get("content", "")):
            matched.append(
                {
                    **q,
                    "parsed_quote": quote_text,
                    "parsed_attribution": attribution_name,
                    "parsed_attribution_id": attribution_id,
                }
            )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(matched, f, indent=2, ensure_ascii=False)

    print(f"{len(matched)} quote(s) extracted from {len(quotes)} messages -> filtered_quotes.json")


if __name__ == "__main__":
    main()
