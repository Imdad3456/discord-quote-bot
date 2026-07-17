"""Extract (quote, attributed_name) pairs from a previous quote-book .docx.

Usage: python tools/extract_quotebook.py path/to/book.docx
Writes previous_quotebook.json next to the input file's basename in this folder.
"""
import json
import os
import re
import sys

import docx

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(HERE, "previous_quotebook.json")

QUOTE_LINE = re.compile(r'^[“"](.+?)[”"]\s*[-–—]\s*(.+)$')


def extract(path):
    document = docx.Document(path)
    entries = []
    skipped = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        match = QUOTE_LINE.match(text)
        if match:
            quote, name = match.groups()
            entries.append({"quote": quote.strip(), "name": name.strip()})
        else:
            skipped.append(text)
    return entries, skipped


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python extract_quotebook.py path/to/book.docx")
    entries, skipped = extract(sys.argv[1])
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    print(f"Extracted {len(entries)} quote/name pairs -> {OUTPUT_FILE}")
    print(f"Skipped {len(skipped)} non-matching lines (titles, headers, etc.):")
    for s in skipped:
        print(f"  - {s[:80]}")
