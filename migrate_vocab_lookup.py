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
from db import get_connection

DB_PATH = os.environ.get("SRS_DB_PATH", "data/srs.db")


def main():
    global DB_PATH
    if len(sys.argv) > 1:
        DB_PATH = sys.argv[1]

    lookup_path = os.path.join(os.path.dirname(DB_PATH), "vocab_lookup.json")
    if not os.path.exists(lookup_path):
        print(f"Lookup file not found: {lookup_path}")
        sys.exit(1)

    with open(lookup_path, "r", encoding="utf-8") as f:
        lookup = json.load(f)

    conn = get_connection()

    # Find vocab cards with empty pinyin (from COVERED.md) or placeholder backs
    rows = conn.execute(
        """SELECT id, front, back, pinyin FROM cards
           WHERE card_type='vocab'
             AND ((pinyin IS NULL OR pinyin = '') OR back LIKE '(%')"""
    ).fetchall()

    updated = 0
    skipped_no_lookup = 0
    for card_id, front, old_back, old_pinyin in rows:
        entry = lookup.get(front)
        if not entry:
            skipped_no_lookup += 1
            continue

        pinyin = entry.get("pinyin", "")
        meaning = entry.get("meaning", "")
        if not pinyin or not meaning:
            skipped_no_lookup += 1
            continue

        conn.execute(
            "UPDATE cards SET back = ?, pinyin = ? WHERE id = ?",
            (meaning, pinyin, card_id),
        )
        updated += 1

    conn.commit()
    conn.close()

    print(f"Updated {updated} cards with pinyin and English meaning.")
    print(f"Skipped {skipped_no_lookup} cards (not found in vocab_lookup.json).")
    # Note: some exercise-file grammar words (e.g. 过, 把) may have pinyin but
    # placeholder backs — they are included in the search above.
    print("Done.")


if __name__ == "__main__":
    main()
