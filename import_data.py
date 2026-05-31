#!/usr/bin/env python3
"""Import exercise data into SQLite database for the SRS app."""

import re
import os
import sqlite3
import sys
from datetime import datetime, date

EXERCISES_DIR = os.environ.get(
    "LEARNING_CHINESE_DIR",
    "../Learning-Chinese",
)
DB_PATH = os.environ.get(
    "SRS_DB_PATH",
    "data/srs.db",
)


def get_exercise_files():
    """Find all daily_exercise_N.md files, sorted by day number."""
    files = []
    for f in os.listdir(EXERCISES_DIR):
        m = re.match(r"daily_exercise_(\d+)\.md", f)
        if m:
            files.append((int(m.group(1)), os.path.join(EXERCISES_DIR, f)))
    return sorted(files, key=lambda x: x[0])


def parse_new_vocab(content):
    """Parse New Vocabulary table. Returns list of (char, pinyin, meaning)."""
    vocab = []
    # Find "## New Vocabulary" section
    m = re.search(r"## New Vocabulary\s*\n((?:\|.*?\|\s*.*?\|\s*.*?\|\s*?\n)+)", content, re.DOTALL)
    if not m:
        return vocab
    
    table_text = m.group(1)
    lines = table_text.strip().split("\n")
    
    # Find the header separator line to determine column count
    header_sep = None
    for i, line in enumerate(lines):
        sl = line.strip()
        if sl.startswith("|---") or sl.startswith("|----"):
            header_sep = i
            break
        # Also handle space-padded separators: | --- |, | --------- |
        if sl.startswith("|") and re.search(r"\|[ -]+\|", sl):
            parts = [c.strip() for c in sl.split("|")]
            parts = [c for c in parts if c]
            if len(parts) >= 1 and all(re.match(r"^-+$", p) for p in parts):
                header_sep = i
                break
    
    if header_sep is None:
        return vocab
    
    data_lines = lines[header_sep+1:]
    
    for line in data_lines:
        line = line.strip()
        if not line.startswith("|") or line.count("|") < 2:
            continue
        
        cells = [c.strip() for c in line.split("|")]
        # Remove empty first/last from split
        cells = [c for c in cells if c != ""]
        
        if len(cells) >= 3:
            char = cells[0].strip()
            pinyin = cells[1].strip() if len(cells) > 1 else ""
            meaning = cells[2].strip() if len(cells) > 2 else ""
            # Clean markdown links
            char = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', char)
            pinyin = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', pinyin)
            meaning = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', meaning)
            if char and meaning:
                vocab.append((char, pinyin, meaning))
    
    return vocab


def parse_grammar_patterns(content, day_num):
    """Parse grammar patterns from exercise. Returns list of (name, description)."""
    patterns = []
    
    # Find all Grammar Pattern sections
    # Pattern: ## Grammar Pattern [N:] Title
    for m in re.finditer(
        r"## Grammar Pattern[^:]*:\s*(.+?)\n(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL,
    ):
        title = m.group(1).strip()
        body = m.group(2).strip()
        patterns.append((title, body))
    
    return patterns


def parse_useful_phrases(content):
    """Parse Useful Phrases section. Returns list of (chinese, english)."""
    phrases = []
    m = re.search(r"## Useful Phrases\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if not m:
        return phrases
    
    body = m.group(1)
    for line in body.split("\n"):
        line = line.strip()
        # Lines like: - **text** — translation
        m2 = re.match(r"-\s*\*\*(.*?)\*\*\s*[—–-]\s*(.*)", line)
        if m2:
            chinese = m2.group(1).strip()
            english = m2.group(2).strip()
            phrases.append((chinese, english))
        # Lines like: - text
        elif line.startswith("- ") and "—" in line:
            parts = line[2:].split("—", 1)
            chinese = parts[0].strip().strip("*").strip()
            english = parts[1].strip()
            phrases.append((chinese, english))
    
    return phrases


def parse_theme(content):
    """Extract theme name."""
    m = re.search(r"## Theme:\s*(.+)", content)
    if m:
        return m.group(1).strip()
    # Fallback: review days use "Days reviewed:" line
    m = re.search(r"## Review Focus\s*\n.*?Days? reviewed:\s*(.+?)(?:\n|$)", content, re.DOTALL)
    if m:
        return "Review: " + m.group(1).strip()
    # From title line
    m = re.search(r"^## Theme:\s*(.+)", content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return ""


def extract_day_number(filename):
    m = re.search(r"daily_exercise_(\d+)\.md", filename)
    return int(m.group(1)) if m else 0


def parse_vocab_warmup(content):
    """Parse warmup vocabulary - these are review words already covered."""
    vocab = []
    m = re.search(r"## Vocabulary Warm-Up[^#]*?\n((?:\|.*?\|\s*.*?\|\s*.*?\|\s*.*?\n)+)", content, re.DOTALL)
    if not m:
        return vocab
    
    table_text = m.group(1)
    lines = table_text.strip().split("\n")
    
    # Find header separator
    header_sep = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|---"):
            header_sep = i
            break
    
    if header_sep is None:
        return vocab
    
    data_lines = lines[header_sep+1:]
    
    for line in data_lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c != ""]
        if len(cells) >= 2:
            char = cells[0].strip()
            char = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', char)
            meaning = cells[1].strip() if len(cells) > 1 else ""
            meaning = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', meaning)
            if char and meaning:
                first_seen = ""
                if len(cells) >= 3:
                    first_seen = cells[2].strip()
                vocab.append((char, "", meaning, first_seen))
    
    return vocab


def parse_covered_grammar(filepath):
    """Parse COVERED.md for grammar pattern descriptions."""
    patterns = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return patterns
    
    # Find "Grammar Patterns" section
    m = re.search(r"## Grammar Patterns.*?\n(.*?)(?=\n## Vocabulary|\Z)", content, re.DOTALL)
    if not m:
        return patterns
    
    body = m.group(1)
    for line in body.split("\n"):
        pass  # COVERED.md grammar format is complex, skip for now
    
    return patterns


def parse_covered_vocab(filepath):
    """Parse COVERED.md for vocabulary categories."""
    vocab = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return vocab
    
    # Find "Vocabulary" section
    m = re.search(r"## Vocabulary\s*\n(.*)", content, re.DOTALL)
    if not m:
        return vocab
    
    body = m.group(1)
    # Extract all Chinese characters mentioned (simplified approach)
    # Each line in vocab section has words like: 现, 在, 几点, etc.
    # We'll parse the themed sub-sections
    
    current_category = "General"
    for line in body.split("\n"):
        sm = re.match(r"^###\s+(.+)", line)
        if sm:
            current_category = sm.group(1).strip()
        
        # Extract Chinese words (sequence of Chinese characters)
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', line)
        for w in chinese_words:
            if w not in [c[0] for c in vocab]:
                vocab.append((w, current_category))
    
    return vocab


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_type TEXT NOT NULL CHECK(card_type IN ('vocab', 'grammar', 'phrase')),
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            pinyin TEXT DEFAULT '',
            category TEXT DEFAULT '',
            source_day INTEGER DEFAULT 0,
            theme TEXT DEFAULT '',
            easiness REAL DEFAULT 2.5,
            interval INTEGER DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            next_review TEXT DEFAULT (date('now')),
            last_reviewed TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS themes (
            day_number INTEGER NOT NULL UNIQUE,
            theme_name TEXT NOT NULL,
            PRIMARY KEY (day_number)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    
    # Index for fast review queries
    # Natural key for upsert — a (card_type, front) pair is unique
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cards_key
        ON cards(card_type, front)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cards_next_review 
        ON cards(next_review, is_active)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cards_card_type 
        ON cards(card_type)
    """)


def upsert_card(cursor, card_type, front, back, pinyin, category, source_day, theme):
    """Insert a card, or update its content fields if it already exists.
    
    Preserves SRS state (easiness, interval, repetitions, next_review) on conflict.
    Exercise-file meanings (back) always replace COVERED.md placeholders.
    """
    cursor.execute("""
        INSERT INTO cards (card_type, front, back, pinyin, category, source_day, theme)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(card_type, front) DO UPDATE SET
            back          = excluded.back,
            pinyin        = excluded.pinyin,
            source_day    = excluded.source_day,
            category      = excluded.category,
            theme         = excluded.theme,
            is_active     = 1
    """, (card_type, front, back, pinyin, category, source_day, theme))


def import_exercises(conn):
    """Parse all exercise files and populate the database.

    When an exercise file is rewritten (e.g. a student changes the theme),
    cards that previously belonged to that exercise but are no longer in its
    content are deactivated (is_active = 0). This keeps the database in sync
    with the current exercise files without ever deleting data.
    """
    cursor = conn.cursor()
    
    files = get_exercise_files()
    print(f"Found {len(files)} exercise files")
    
    # Track (card_type, front) pairs already seen across all files so far.
    # When a card appears in multiple exercises, the EARLIEST exercise wins
    # for source attribution. This prevents later exercises from claiming a
    # card and then having it deactivated when that later exercise is rewritten.
    seen = set()
    
    total_deactivated = 0
    
    for day_num, filepath in files:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        theme = parse_theme(content)
        
        # Upsert theme
        cursor.execute(
            "INSERT OR REPLACE INTO themes (day_number, theme_name) VALUES (?, ?)",
            (day_num, theme),
        )
        
        # Track which (card_type, front) pairs this exercise currently produces.
        # After upserting, any active card with source_day == day_num that is
        # NOT in this set will be deactivated — this handles exercise rewrites
        # (e.g. when a student changes the theme and regenerates the file).
        day_keys = set()
        
        # Vocabulary
        for char, pinyin, meaning in parse_new_vocab(content):
            key = ("vocab", char)
            day_keys.add(key)
            if key not in seen:
                seen.add(key)
                upsert_card(cursor, "vocab", char, meaning, pinyin, theme, day_num, theme)
        
        # Grammar patterns
        for title, body in parse_grammar_patterns(content, day_num):
            key = ("grammar", title)
            day_keys.add(key)
            if key not in seen:
                seen.add(key)
                back = title
                for line in body.split("\n"):
                    line = line.strip()
                    if line.startswith("- **") or line.startswith("- "):
                        back = title + " — " + line.lstrip("- ").strip("*")
                        break
                    elif line and not line.startswith("**") and not line.startswith("Structure"):
                        back = title + " — " + line[:100]
                        break
                upsert_card(cursor, "grammar", title, body[:500], "", theme, day_num, theme)
        
        # Useful phrases
        for chinese, english in parse_useful_phrases(content):
            key = ("phrase", chinese)
            day_keys.add(key)
            if key not in seen:
                seen.add(key)
                upsert_card(cursor, "phrase", chinese, english, "", theme, day_num, theme)
        
        # Deactivate cards that previously belonged to this exercise day but
        # are no longer in its content (exercise was rewritten).
        # Only affects cards whose source_day matches the current day, so a
        # card that appeared in an earlier exercise first is safe even if it
        # appears in a later exercise's day_keys as well.
        existing = cursor.execute(
            "SELECT card_type, front FROM cards WHERE source_day = ? AND is_active = 1",
            (day_num,),
        ).fetchall()
        
        deactivated = 0
        for card_type, front in existing:
            if (card_type, front) not in day_keys:
                cursor.execute(
                    "UPDATE cards SET is_active = 0 WHERE card_type = ? AND front = ? AND source_day = ?",
                    (card_type, front, day_num),
                )
                deactivated += 1
        
        if deactivated:
            print(f"  Day {day_num}: deactivated {deactivated} card(s) removed from rewritten exercise")
        total_deactivated += deactivated
    
    conn.commit()
    
    # Report
    total = cursor.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    active = cursor.execute("SELECT COUNT(*) FROM cards WHERE is_active = 1").fetchone()[0]
    print(f"  Active cards: {active}")
    print(f"  Total cards (incl. deactivated): {total}")
    if total_deactivated:
        print(f"  Deactivated this run: {total_deactivated}")


def insert_if_missing(cursor, card_type, front, back, pinyin, category, source_day, theme):
    """Insert a card ONLY if it doesn't already exist (no overwrite)."""
    cursor.execute("""
        INSERT INTO cards (card_type, front, back, pinyin, category, source_day, theme)
        SELECT ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM cards WHERE card_type = ? AND front = ?
        )
    """, (card_type, front, back, pinyin, category, source_day, theme,
          card_type, front))


def add_additional_vocab_from_covered(conn):
    """Insert vocabulary from COVERED.md that doesn't already exist.
    
    Uses insert_if_missing so exercise-file definitions always take priority.
    """
    covered_path = os.path.join(EXERCISES_DIR, "COVERED.md")
    if not os.path.exists(covered_path):
        return
    
    cursor = conn.cursor()
    covered_vocab = parse_covered_vocab(covered_path)
    
    before = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    for char, category in covered_vocab:
        insert_if_missing(cursor, "vocab", char, f"({category})", "", category, 0, "")
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    added = after - before
    print(f"Added {added} new items from COVERED.md ({len(covered_vocab) - added} already existed from exercise files)")


def main():
    global EXERCISES_DIR, DB_PATH
    
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) > 0:
        EXERCISES_DIR = args[0]
    if len(args) > 1:
        DB_PATH = args[1]
    
    if "--help" in sys.argv or "-h" in sys.argv:
        print(f"Usage: uv run import_data.py [EXERCISES_DIR] [DB_PATH]")
        print(f"  EXERCISES_DIR  Path to Learning-Chinese directory")
        print(f"                 (default: {EXERCISES_DIR})")
        print(f"  DB_PATH        Path for SQLite database")
        print(f"                 (default: {DB_PATH})")
        print(f"Environment:")
        print(f"  LEARNING_CHINESE_DIR  Override exercises directory")
        print(f"  SRS_DB_PATH           Override database path")
        sys.exit(0)
    
    if not os.path.isdir(EXERCISES_DIR):
        print(f"Error: exercises directory not found: {EXERCISES_DIR}", file=sys.stderr)
        print("Pass the path as an argument or set LEARNING_CHINESE_DIR", file=sys.stderr)
        sys.exit(1)
    
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    print(f"Importing from: {EXERCISES_DIR}")
    print(f"Database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    
    # Do NOT wipe data — upsert preserves existing SRS state
    
    import_exercises(conn)
    add_additional_vocab_from_covered(conn)
    
    # Get counts
    cursor = conn.cursor()
    counts = {}
    for row in cursor.execute("SELECT card_type, COUNT(*) FROM cards GROUP BY card_type"):
        counts[row[0]] = row[1]
    
    total = cursor.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    theme_count = cursor.execute("SELECT COUNT(*) FROM themes").fetchone()[0]
    
    print(f"\nImport complete!")
    print(f"  Total cards: {total}")
    print(f"  - Vocab: {counts.get('vocab', 0)}")
    print(f"  - Grammar: {counts.get('grammar', 0)}")
    print(f"  - Phrases: {counts.get('phrase', 0)}")
    print(f"  Themes (exercise days): {theme_count}")
    
    conn.close()


if __name__ == "__main__":
    main()
