# AGENTS.md — AI Agent Guide for learning-chinese-srs

## Repository Purpose

A standalone spaced-repetition web app that extracts Chinese vocabulary, grammar, and phrases from the [Learning-Chinese](https://github.com/davidbcn07/Learning-Chinese) exercise vault and presents them as flashcards using the SM-2 algorithm.

This is a separate project from the Learning-Chinese workflow. It reads from the exercise files but never writes to them.

## Critical Files

| File | Purpose |
|------|---------|
| File | Purpose |
|------|---------|
| `import_data.py` | Parses `daily_exercise_*.md` files and upserts cards into SQLite. Run after every new exercise batch. |
| `app.py` | Flask server: API endpoints + SM-2 logic. No modifications needed for routine operation. |
| `templates/index.html` | Single-page frontend (dashboard, review UI, card browser). All JS + CSS inline. |
| `data/srs.db` | SQLite database (gitignored). Contains cards + themes tables. SRS state lives here. |
| `data/vocab_lookup.json` | Supplementary pinyin/meaning data for vocab listed only in `COVERED.md` (never in a `## New Vocabulary` table). |
| `migrate_vocab_lookup.py` | One-time migration to backfill existing cards with data from `vocab_lookup.json`. Run once after adding the file. |
| `pyproject.toml` | uv project config. Dependencies: flask. |

## Agent Workflow

### 1. Setting Up

```bash
cd /path/to/learning-chinese-srs
uv sync                     # Install dependencies
uv run import_data.py       # Import cards from the Learning-Chinese directory
uv run app.py               # Start the server
```

### 2. After The Learning-Chinese Repo Adds New Exercises

```bash
uv run import_data.py
```

This is safe to run any time:
- **New cards** are added for new vocabulary/grammar/phrases
- **Existing cards** have their content fields (meaning, pinyin, theme) refreshed
- **SRS state** (easiness, interval, repetitions, next_review) is **never touched**
- **Removed cards** from rewritten exercises are deactivated (`is_active = 0`) — see note below
- If the Learning-Chinese directory is elsewhere, pass the path as an argument

> **Exercise rewrites**: If an exercise file is rewritten (e.g. the student changes the theme),
> any card that was originally sourced from that exercise but is no longer in its content
> will be **deactivated** (not deleted). This keeps the DB in sync without losing data.
> Deactivated cards are hidden from review but remain in the database for recovery.
> To restore a deactivated card, set `is_active = 1` manually or re-add it to an exercise.

### 3. When Modifying the Parser

If exercise file formats change (different table layouts, new sections), edit `import_data.py`:

- `parse_new_vocab()` — parses `## New Vocabulary` tables
- `parse_grammar_patterns()` — parses `## Grammar Pattern` sections
- `parse_useful_phrases()` — parses `## Useful Phrases` sections
- `parse_theme()` — extracts theme name (also handles review days)
- `parse_vocab_warmup()` — parses review vocabulary tables (unused in main flow)

After any parser change, re-run `import_data.py`. The upsert logic (`ON CONFLICT(card_type, front)`) means re-importing is idempotent.

### 3a. COVERED.md Vocabulary Without Pinyin/Translation

Some vocabulary (e.g. `口疮`, `果断`, `漱口`) is listed in `COVERED.md` but was never formally
introduced in a `## New Vocabulary` table. When imported from COVERED.md, these words would get
empty pinyin and a category placeholder as the meaning.

To fix this, edit `data/vocab_lookup.json` and add an entry for the word with `pinyin` and `meaning`.
On next `uv run import_data.py`, the lookup is automatically used. For existing cards already in the
database, run:

```bash
uv run migrate_vocab_lookup.py
```

### 4. To Reset a Single Card

```bash
curl -X POST http://localhost:5000/api/reset \
  -H 'Content-Type: application/json' \
  -d '{"card_id": 123}'
```

### 5. Naming & Constraints

- Card keys are `(card_type, front)` — this is the unique constraint for upsert
- `card_type` is one of: `vocab`, `grammar`, `phrase`
- `is_active` controls whether a card appears in reviews (1 = active, 0 = deactivated)
- SM-2 easiness factor is clamped to ≥ 1.3
- Failed reviews (quality < 3) reset interval to 1 day and repetitions to 0
- The `upsert_card()` helper preserves SRS columns on conflict

## Path Configuration

All paths are configurable — never hardcode absolute paths.

| Tool | Default | Env Var | CLI Arg |
|------|---------|---------|---------|
| `import_data.py` (exercises) | `../Learning-Chinese` | `LEARNING_CHINESE_DIR` | 1st positional |
| `import_data.py` (database) | `data/srs.db` | `SRS_DB_PATH` | 2nd positional |
| `app.py` (database) | `data/srs.db` | `SRS_DB_PATH` | — |

Paths are resolved relative to the current working directory.

## Helper Scripts

| Script | Purpose |
|--------|---------|
| `uv run import_data.py` | Import/refresh all cards from exercise files (+ COVERED.md). |
| `uv run app.py` | Start the Flask server. |
| `uv run migrate_vocab_lookup.py` | Backfill pinyin/meaning for cards that were imported from COVERED.md without them. |

## Design Decisions

- **Single-file frontend**: Everything is in `index.html`. No build step, no npm. Easy to tweak.
- **No ORM**: Raw SQLite + Flask. Simple and transparent.
- **Incremental import**: Deleting and re-inserting all cards would wipe SRS state. The upsert approach (`ON CONFLICT DO UPDATE SET back/pinyin/category/theme...`) is intentional.
- **Exercise rewrites**: After each exercise is processed, cards with `source_day == current_day` that
  are no longer in that exercise's content get deactivated (`is_active = 0`). This handles the common
  scenario where a student rewrites the latest exercise because the theme wasn't relevant.
  Cards from earlier exercises keep their `source_day` even if they also appear in a later exercise
  (the global `seen` set ensures first-source attribution), so rewriting a later exercise does not
  affect cards introduced earlier. Deactivated cards remain in the database with SRS state intact.
- **Markdown rendering**: Grammar card backs contain markdown (`**bold**`, `> blockquotes`). `renderMarkdown()` in the frontend handles this.
- **No authentication**: Runs on localhost only. The WARNING about development server is expected — this is a personal tool.
