"""Database abstraction — local SQLite or Turso/libSQL (Vercel).

Usage:
    from db import get_connection
    conn = get_connection()
    rows = conn.execute("SELECT * FROM cards").fetchall()
    for row in rows:
        print(row["front"], row["back"])   # dict access
        print(row[0], row[1])              # tuple access  (same query)

The returned connection works like a sqlite3 connection with row_factory = Row.
Set TURSO_DATABASE_URL + TURSO_AUTH_TOKEN in env to use Turso (Vercel/serverless).
Otherwise uses local SQLite at SRS_DB_PATH (default: data/srs.db).
"""

import os

# ── Auto-load .env if present (no dependency on python-dotenv) ─────────────
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _val = _val.strip().strip("\"'").strip()
                os.environ.setdefault(_key.strip(), _val)

SRS_DB_PATH = os.environ.get("SRS_DB_PATH", "data/srs.db")
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")


def get_connection():
    """Get a database connection.

    Returns a connection whose execute() results support both
    row["key"] and row[0] access — compatible with sqlite3.Row.

    - If TURSO_DATABASE_URL is set → connects to Turso (Vercel/serverless)
    - Otherwise → local SQLite file at SRS_DB_PATH
    """
    if TURSO_URL:
        return _turso_connect()
    return _sqlite_connect()


# ── SQLite (local dev) ──────────────────────────────────────────────────────


def _sqlite_connect():
    import sqlite3
    os.makedirs(os.path.dirname(SRS_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(SRS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Turso / libSQL remote (Vercel) ──────────────────────────────────────────


def _turso_connect():
    import libsql
    raw = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    return _TursoConnection(raw)


# ── Compatibility wrappers ──────────────────────────────────────────────────


class _Row:
    """A row that supports both row[0] (index) and row["key"] (dict) access,
    matching the sqlite3.Row interface."""

    __slots__ = ("_data", "_cols", "_col_map")

    def __init__(self, data, columns):
        self._data = data
        self._cols = columns
        self._col_map = {c: i for i, c in enumerate(columns)}

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._data[self._col_map[key]]
        return self._data[key]

    def keys(self):
        return self._cols

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"<_Row {dict(zip(self._cols, self._data))}>"


class _TursoCursor:
    """Wraps a libSQL Result object with a sqlite3.Cursor-like interface."""

    def __init__(self, raw_conn, result=None):
        self._raw = raw_conn
        self._result = result
        self._cols = (
            [d[0] for d in (result.description or [])] if result else []
        )
        self._all_rows = None
        self._index = 0
        self.description = result.description if result else None

    # ── sqlite3.Cursor-compatible execute (for cursor() path) ──────────

    def execute(self, sql, parameters=None):
        if parameters is None:
            parameters = ()
        self._result = self._raw.execute(sql, parameters)
        self._cols = [d[0] for d in (self._result.description or [])]
        self._all_rows = None
        self._index = 0
        self.description = self._result.description
        return self

    # ── Row fetching ───────────────────────────────────────────────────

    def fetchone(self):
        if self._all_rows is not None:
            return None  # already consumed by __iter__ or fetchall
        row = self._result.fetchone()
        if row is None:
            return None
        if not self._cols:
            return row  # scalar result — tuple is fine, no dict access needed
        return _Row(row, self._cols)

    def fetchall(self):
        if self._all_rows is not None:
            return self._all_rows
        rows = self._result.fetchall()
        if not self._cols:
            return rows
        self._all_rows = [_Row(r, self._cols) for r in rows]
        return self._all_rows

    def __iter__(self):
        self._all_rows = self.fetchall()
        self._index = 0
        return self

    def __next__(self):
        if self._index >= len(self._all_rows):
            raise StopIteration
        row = self._all_rows[self._index]
        self._index += 1
        return row


class _TursoConnection:
    """Wraps a libSQL Connection to expose the same API as a sqlite3 connection."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, parameters=None):
        if parameters is None:
            parameters = ()
        result = self._raw.execute(sql, parameters)
        return _TursoCursor(self._raw, result)

    def cursor(self):
        """Return a cursor for the connection (sqlite3 compatibility)."""
        return _TursoCursor(self._raw)

    def commit(self):
        self._raw.commit()

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass
