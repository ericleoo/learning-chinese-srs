#!/usr/bin/env python3
"""Migrate existing SQLite data to Turso, preserving SRS state.

Usage:
    export TURSO_DATABASE_URL="libsql://your-db.turso.io"
    export TURSO_AUTH_TOKEN="your-token"
    uv run migrate_to_turso.py [SQLITE_PATH]

This copies ALL data including SRS state (easiness, interval, repetitions,
next_review, last_reviewed) from the local SQLite database to Turso.
Run once after setting up your Turso database.
"""

import json
import os
import sys

DB_PATH = os.environ.get("SRS_DB_PATH", "data/srs.db")


def dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def migrate():
    global DB_PATH

    if len(sys.argv) > 1:
        DB_PATH = sys.argv[1]

    if not os.path.exists(DB_PATH):
        print(f"Error: SQLite database not found: {DB_PATH}")
        sys.exit(1)

    import sqlite3
    from db import get_connection, TURSO_URL

    if not TURSO_URL:
        print("Error: TURSO_DATABASE_URL not set (run with .env or export it).")
        sys.exit(1)

    print(f"Source: {DB_PATH} (SQLite)")
    print(f"Target: {TURSO_URL[:60]}... (Turso)")

    # ── Read from SQLite ──────────────────────────────────────────────
    src = sqlite3.connect(DB_PATH)
    src.row_factory = dict_factory

    tables = ["cards", "themes", "categories"]
    data = {}
    for table in tables:
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        data[table] = rows
        print(f"  {table}: {len(rows)} rows")
    src.close()

    # ── Write to Turso ────────────────────────────────────────────────
    dest = get_connection()

    # Create schema idempotently
    schema_statements = [
        "CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY AUTOINCREMENT, card_type TEXT NOT NULL CHECK(card_type IN ('vocab', 'grammar', 'phrase')), front TEXT NOT NULL, back TEXT NOT NULL, pinyin TEXT DEFAULT '', category TEXT DEFAULT '', source_day INTEGER DEFAULT 0, theme TEXT DEFAULT '', easiness REAL DEFAULT 2.5, interval INTEGER DEFAULT 0, repetitions INTEGER DEFAULT 0, next_review TEXT DEFAULT (date('now')), last_reviewed TEXT, is_active INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS themes (day_number INTEGER NOT NULL UNIQUE, theme_name TEXT NOT NULL, PRIMARY KEY (day_number))",
        "CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cards_key ON cards(card_type, front)",
        "CREATE INDEX IF NOT EXISTS idx_cards_next_review ON cards(next_review, is_active)",
        "CREATE INDEX IF NOT EXISTS idx_cards_card_type ON cards(card_type)",
    ]

    for sql in schema_statements:
        try:
            dest.execute(sql)
        except Exception as e:
            print(f"  Warning: schema: {e}")

    # Delete any existing data so we start fresh
    for table in tables:
        if data[table]:
            dest.execute(f"DELETE FROM {table}")
    dest.commit()

    # Insert data — batch rows into multi-value INSERTs to minimise HTTP round-trips
    batch_size = 20  # smaller batches = less risk of hitting limits
    for table in tables:
        rows = data[table]
        if not rows:
            print(f"  No data for {table}, skipping")
            continue

        cols = list(rows[0].keys())
        col_names = ", ".join(cols)

        inserted = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            row_placeholders = []
            flat_values = []
            for row in batch:
                row_placeholders.append("(" + ", ".join("?" for _ in cols) + ")")
                flat_values.extend(tuple(row[c] for c in cols))

            all_placeholders = ", ".join(row_placeholders)
            sql = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES {all_placeholders}"

            try:
                dest.execute(sql, tuple(flat_values))
                inserted += len(batch)
            except Exception as e:
                print(f"  Error inserting {table} batch {i // batch_size}: {e}")
                # Try individual rows as fallback
                for row in batch:
                    vals = tuple(row[c] for c in cols)
                    try:
                        dest.execute(
                            f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({', '.join('?' for _ in cols)})",
                            vals,
                        )
                        inserted += 1
                    except Exception as e2:
                        print(f"    Skipped row: {e2}")

        # Commit after each table
        dest.commit()
        print(f"  Inserted {inserted} rows into {table}")

    # Verify
    print()
    for table in tables:
        count = dest.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  Turso {table}: {count} rows")

    active = dest.execute("SELECT COUNT(*) FROM cards WHERE is_active = 1").fetchone()[0]
    total = dest.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    print(f"\n  Cards: {active} active, {total} total")

    dest.close()
    print("\n✅ Migration complete!")


if __name__ == "__main__":
    migrate()
