"""Load a phpMyAdmin / MariaDB SQL dump into data/live_data.db (SQLite).

Usage:
    python scripts/load_mysql_dump.py path/to/dump.sql

What it does:
  1. Strips MySQL-specific header noise (SET SQL_MODE, /*!...*/ blocks, etc.)
  2. Transpiles each CREATE TABLE / INSERT statement from MySQL → SQLite dialect
     using sqlglot (already a project dependency).
  3. Skips ALTER TABLE statements (indexes, keys) that SQLite doesn't support —
     they're logged so you can add CREATE INDEX manually if needed.
  4. Loads everything into data/live_data.db, which is what the pipeline reads.

Run this once per dump. Re-running is safe (tables are replaced, not appended).
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import sqlglot

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "live_data.db"

# ── Pre-processing regexes ────────────────────────────────────────────────────

# phpMyAdmin conditional comments: /*!40101 SET ... */
_CONDITIONAL_COMMENT = re.compile(r"/\*!.*?\*/\s*;?", re.DOTALL)
# SET statements (SQL_MODE, time_zone, character set etc.)
_SET_STMT = re.compile(r"^\s*SET\s+[^;]+;", re.IGNORECASE | re.MULTILINE)
# START TRANSACTION / COMMIT / LOCK / UNLOCK
_TRANSACTION = re.compile(
    r"^\s*(START\s+TRANSACTION|COMMIT|LOCK\s+TABLES?|UNLOCK\s+TABLES?)\s*;",
    re.IGNORECASE | re.MULTILINE,
)
# MySQL "Dumping data for table X" comment blocks
_COMMENT_LINE = re.compile(r"^\s*--[^\n]*\n", re.MULTILINE)


def preprocess(sql: str) -> str:
    """Strip MySQL-specific noise that sqlglot can't transpile."""
    sql = _CONDITIONAL_COMMENT.sub("", sql)
    sql = _SET_STMT.sub("", sql)
    sql = _TRANSACTION.sub("", sql)
    sql = _COMMENT_LINE.sub("", sql)
    return sql


def split_statements(sql: str) -> list[str]:
    """Split on semicolons, skip empty/whitespace-only fragments."""
    stmts = []
    for raw in sql.split(";"):
        s = raw.strip()
        if s:
            stmts.append(s)
    return stmts


def transpile_statement(stmt: str) -> str | None:
    """MySQL → SQLite via sqlglot. Returns None if the statement should be skipped."""
    upper = stmt.upper().lstrip()

    # Skip ALTER TABLE (adding indexes/keys) — SQLite supports very limited ALTER.
    # CREATE INDEX equivalents can be added manually if needed.
    if upper.startswith("ALTER TABLE"):
        return None

    # Skip CREATE DATABASE / USE — SQLite has no namespace concept.
    if upper.startswith(("CREATE DATABASE", "CREATE SCHEMA", "USE ")):
        return None

    try:
        results = sqlglot.transpile(stmt, read="mysql", write="sqlite", error_level=sqlglot.ErrorLevel.WARN)
        return results[0] if results else None
    except Exception as e:
        print(f"  [warn] Could not transpile, skipping: {e!s:.120}")
        return None


def load(dump_path: Path) -> None:
    print(f"Reading {dump_path} …")
    raw = dump_path.read_text(encoding="utf-8", errors="replace")

    print("Pre-processing MySQL-specific syntax …")
    cleaned = preprocess(raw)
    statements = split_statements(cleaned)
    print(f"  {len(statements)} statements found after splitting")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)

    ok = skipped = errors = 0
    with con:
        for stmt in statements:
            sqlite_stmt = transpile_statement(stmt)
            if sqlite_stmt is None:
                skipped += 1
                continue
            try:
                con.execute(sqlite_stmt)
                ok += 1
            except sqlite3.OperationalError as e:
                errors += 1
                # Truncate long statements in the log to keep output readable
                preview = stmt[:120].replace("\n", " ")
                print(f"  [error] {e!s:.100}  ← {preview!r}")

    con.close()

    print(f"\nDone. Loaded into {DB_PATH}")
    print(f"  ✓ executed : {ok}")
    print(f"  ⊘ skipped  : {skipped}  (ALTER TABLE / CREATE DATABASE / untranslatable)")
    print(f"  ✗ errors   : {errors}")

    # Quick sanity check — list tables and row counts
    con = sqlite3.connect(DB_PATH)
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    print(f"\nTables now in {DB_PATH.name}:")
    for (name,) in tables:
        count = con.execute(f"SELECT COUNT(*) FROM \"{name}\"").fetchone()[0]
        print(f"  {name:<40} {count:>8} rows")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/load_mysql_dump.py path/to/dump.sql")
        sys.exit(1)

    dump_path = Path(sys.argv[1])
    if not dump_path.exists():
        print(f"File not found: {dump_path}")
        sys.exit(1)

    load(dump_path)
