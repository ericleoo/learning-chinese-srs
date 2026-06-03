#!/usr/bin/env python3
"""One-time migration: update existing vocab cards with pinyin/meaning from vocab_lookup.json.

Cards imported from COVERED.md without pinyin or translation get their back and pinyin
fields filled in. Skips cards that already have non-empty pinyin (already imported from
exercise files) and skips words not in the lookup.

Usage: uv run migrate_vocab_lookup.py [DB_PATH]
"""

import json
import os
import sys

DB_PATH = os.environ.get("SRS_DB_PATH", "data/srs.db")


def main():
    global DB_PATH
    if len(sys.argv) > 1:
        DB_PATH = sys.argv[1]

    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    lookup_path = os.path.join(os.path.dirname(DB_PATH), "vocab_lookup.json")
    if not os.path.exists(lookup_path):
        print(f"Lookup file not found: {lookup_path}")
        sys.exit(1)

    with open(lookup_path, "r", encoding="utf-8") as f:
        lookup = json.load(f)

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Find vocab cards with empty pinyin (from COVERED.md)
    rows = cur.execute(
        "SELECT id, front, back FROM cards WHERE card_type='vocab' AND (pinyin IS NULL OR pinyin = '')"
    ).fetchall()

    updated = 0
    skipped_no_lookup = 0
    for card_id, front, old_back in rows:
        entry = lookup.get(front)
        if not entry:
            skipped_no_lookup += 1
            continue

        pinyin = entry.get("pinyin", "")
        meaning = entry.get("meaning", "")
        if not pinyin or not meaning:
            skipped_no_lookup += 1
            continue

        cur.execute(
            "UPDATE cards SET back = ?, pinyin = ? WHERE id = ?",
            (meaning, pinyin, card_id),
        )
        updated += 1

    conn.commit()
    conn.close()

    print(f"Updated {updated} cards with pinyin and English meaning.")
    print(f"Skipped {skipped_no_lookup} cards (not found in vocab_lookup.json).")
    print("Done.")


if __name__ == "__main__":
    main()
