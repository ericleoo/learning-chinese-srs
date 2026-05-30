# AGENTS.md — AI Agent Guide for learning-chinese-srs

## Repository Purpose

A standalone spaced-repetition web app that extracts Chinese vocabulary, grammar, and phrases from the [Learning-Chinese](https://github.com/davidbcn07/Learning-Chinese) exercise vault and presents them as flashcards using the SM-2 algorithm.

This is a separate project from the Learning-Chinese workflow. It reads from the exercise files but never writes to them.

## Critical Files

| File | Purpose |
|------|---------|
| `import_data.py` | Parses `daily_exercise_*.md` files and upserts cards into SQLite. Run after every new exercise batch. |
| `app.py` | Flask server: API endpoints + SM-2 logic. No modifications needed for routine operation. |
| `templates/index.html` | Single-page frontend (dashboard, review UI, card browser). All JS + CSS inline. |
| `data/srs.db` | SQLite database (gitignored). Contains cards + themes tables. SRS state lives here. |
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
- If the Learning-Chinese directory is elsewhere, pass the path as an argument

### 3. When Modifying the Parser

If exercise file formats change (different table layouts, new sections), edit `import_data.py`:

- `parse_new_vocab()` — parses `## New Vocabulary` tables
- `parse_grammar_patterns()` — parses `## Grammar Pattern` sections
- `parse_useful_phrases()` — parses `## Useful Phrases` sections
- `parse_theme()` — extracts theme name (also handles review days)
- `parse_vocab_warmup()` — parses review vocabulary tables (unused in main flow)

After any parser change, re-run `import_data.py`. The upsert logic (`ON CONFLICT(card_type, front)`) means re-importing is idempotent.

### 4. To Reset a Single Card

```bash
curl -X POST http://localhost:5000/api/reset \
  -H 'Content-Type: application/json' \
  -d '{"card_id": 123}'
```

### 5. Naming & Constraints

- Card keys are `(card_type, front)` — this is the unique constraint for upsert
- `card_type` is one of: `vocab`, `grammar`, `phrase`
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

None yet. The project is small enough that `uv run import_data.py` and `uv run app.py` are the only commands.

## Design Decisions

- **Single-file frontend**: Everything is in `index.html`. No build step, no npm. Easy to tweak.
- **No ORM**: Raw SQLite + Flask. Simple and transparent.
- **Incremental import**: Deleting and re-inserting all cards would wipe SRS state. The upsert approach (`ON CONFLICT DO UPDATE SET back/pinyin/category/theme...`) is intentional.
- **Markdown rendering**: Grammar card backs contain markdown (`**bold**`, `> blockquotes`). `renderMarkdown()` in the frontend handles this.
- **No authentication**: Runs on localhost only. The WARNING about development server is expected — this is a personal tool.
