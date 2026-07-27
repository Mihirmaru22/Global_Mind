"""Load a phpMyAdmin / MariaDB SQL dump into data/live_data.db (SQLite).

Usage:
    python scripts/load_mysql_dump.py path/to/dump.sql

What it does:
  1. Strips MySQL-specific header noise (SET SQL_MODE, /*!...*/ blocks, etc.)
  2. Tries sqlglot transpilation first (MySQL → SQLite dialect).
  3. If sqlglot fails, falls back to regex-based manual cleanup that handles
     MariaDB-specific syntax sqlglot can't always parse (ENUM, UNSIGNED,
     ENGINE=, COLLATE, COMMENT clauses, etc.).
  4. Skips ALTER TABLE / CREATE DATABASE — those are just indexes/keys and
     SQLite doesn't support them; logged at the end.
  5. Loads everything into data/live_data.db, which is what the pipeline reads.

Re-running is safe — tables are replaced, not appended.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import sqlglot

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "live_data.db"

# ── Pre-processing: strip phpMyAdmin / MySQL header noise ─────────────────────

_CONDITIONAL_COMMENT = re.compile(r"/\*!.*?\*/\s*;?", re.DOTALL)
_SET_STMT = re.compile(r"^\s*SET\s+[^;]+;", re.IGNORECASE | re.MULTILINE)
_TRANSACTION = re.compile(
    r"^\s*(START\s+TRANSACTION|COMMIT|LOCK\s+TABLES?|UNLOCK\s+TABLES?)\s*;",
    re.IGNORECASE | re.MULTILINE,
)
_COMMENT_LINE = re.compile(r"^\s*--[^\n]*\n", re.MULTILINE)


def preprocess(sql: str) -> str:
    sql = _CONDITIONAL_COMMENT.sub("", sql)
    sql = _SET_STMT.sub("", sql)
    sql = _TRANSACTION.sub("", sql)
    sql = _COMMENT_LINE.sub("", sql)
    return sql


def split_statements(sql: str) -> list[str]:
    stmts = []
    for raw in sql.split(";"):
        s = raw.strip()
        if s:
            stmts.append(s)
    return stmts


# ── Manual fallback: regex-clean a MySQL statement into valid SQLite ──────────

# Column-level clauses SQLite doesn't understand
_UNSIGNED = re.compile(r"\bUNSIGNED\b", re.IGNORECASE)
_ZEROFILL = re.compile(r"\bZEROFILL\b", re.IGNORECASE)
_AUTO_INCREMENT = re.compile(r"\bAUTO_INCREMENT\b", re.IGNORECASE)
_CHARACTER_SET = re.compile(r"\bCHARACTER\s+SET\s+\S+", re.IGNORECASE)
_COLLATE_COL = re.compile(r"\bCOLLATE\s+\S+", re.IGNORECASE)
_COMMENT_COL = re.compile(r"\bCOMMENT\s+'[^']*'", re.IGNORECASE)
_ON_UPDATE = re.compile(r"\bON\s+UPDATE\s+\S+", re.IGNORECASE)

# Table-level options after the closing ) of a CREATE TABLE
_TABLE_OPTIONS = re.compile(
    r"\)\s*(ENGINE\s*=\s*\S+|AUTO_INCREMENT\s*=\s*\d+|DEFAULT\s+CHARSET\s*=\s*\S+|"
    r"COLLATE\s*=\s*\S+|ROW_FORMAT\s*=\s*\S+|COMMENT\s*=\s*'[^']*'|"
    r"CHECKSUM\s*=\s*\d+|DELAY_KEY_WRITE\s*=\s*\d+|\s)+\s*$",
    re.IGNORECASE,
)

# ENUM / SET → TEXT
_ENUM_SET = re.compile(r"\b(ENUM|SET)\s*\([^)]+\)", re.IGNORECASE)

# MySQL int types with display width e.g. int(11) → INTEGER
_INT_WIDTH = re.compile(
    r"\b(TINYINT|SMALLINT|MEDIUMINT|BIGINT|INT)\s*\(\d+\)",
    re.IGNORECASE,
)

# Backtick identifiers → double-quoted (SQLite standard)
_BACKTICK = re.compile(r"`([^`]+)`")

# KEY / INDEX lines inside CREATE TABLE that SQLite doesn't support
_KEY_LINE = re.compile(
    r"^\s*(UNIQUE\s+)?(KEY|INDEX)\s+.*$",
    re.IGNORECASE | re.MULTILINE,
)
_PRIMARY_KEY_LINE = re.compile(
    r"^\s*PRIMARY\s+KEY\s*\([^)]+\)\s*,?",
    re.IGNORECASE | re.MULTILINE,
)

# Trailing comma before closing paren (left after removing KEY lines)
_TRAILING_COMMA = re.compile(r",\s*\)", re.DOTALL)


def manual_cleanup(stmt: str) -> str:
    """Best-effort regex cleanup of MySQL syntax that sqlglot couldn't handle."""
    s = stmt

    # Backticks → double quotes
    s = _BACKTICK.sub(r'"\1"', s)

    # Column-level noise
    s = _UNSIGNED.sub("", s)
    s = _ZEROFILL.sub("", s)
    s = _AUTO_INCREMENT.sub("", s)
    s = _CHARACTER_SET.sub("", s)
    s = _COLLATE_COL.sub("", s)
    s = _COMMENT_COL.sub("", s)
    s = _ON_UPDATE.sub("", s)

    # Type replacements
    s = _ENUM_SET.sub("TEXT", s)
    s = _INT_WIDTH.sub(r"\1", s)

    # Remove KEY / INDEX lines inside CREATE TABLE (not PRIMARY KEY)
    s = _KEY_LINE.sub("", s)

    # Remove table-level options after closing paren
    # Match ) followed by table options at end of statement
    s = re.sub(
        r"\)\s*(?:ENGINE\s*=\s*\w+|AUTO_INCREMENT\s*=\s*\d+|DEFAULT\s+CHARSET\s*=\s*\w+|"
        r"COLLATE\s*=\s*\w+|ROW_FORMAT\s*=\s*\w+|COMMENT\s*=\s*'[^']*'|\s)+\s*$",
        ")",
        s,
        flags=re.IGNORECASE,
    )

    # Clean up trailing commas before )
    s = _TRAILING_COMMA.sub(")", s)

    # Collapse multiple blank lines
    s = re.sub(r"\n{3,}", "\n\n", s)

    return s.strip()


def transpile_statement(stmt: str) -> str | None:
    """MySQL → SQLite. Returns None if statement should be skipped entirely."""
    upper = stmt.upper().lstrip()

    if upper.startswith(("ALTER TABLE", "CREATE DATABASE", "CREATE SCHEMA", "USE ")):
        return None

    # Try sqlglot first
    try:
        results = sqlglot.transpile(
            stmt, read="mysql", write="sqlite", error_level=sqlglot.ErrorLevel.WARN
        )
        if results and results[0].strip():
            return results[0]
    except Exception:
        pass

    # sqlglot failed — fall back to manual regex cleanup
    return manual_cleanup(stmt)


def load(dump_path: Path) -> None:
    print(f"Reading {dump_path} …")
    raw = dump_path.read_text(encoding="utf-8", errors="replace")

    print("Pre-processing MySQL-specific syntax …")
    cleaned = preprocess(raw)
    statements = split_statements(cleaned)
    print(f"  {len(statements)} statements found")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)

    ok = skipped = errors = 0
    failed_stmts: list[tuple[str, str]] = []

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
                preview = stmt[:100].replace("\n", " ")
                failed_stmts.append((str(e), preview))

    con.close()

    print(f"\nDone. Loaded into {DB_PATH}")
    print(f"  ✓ executed : {ok}")
    print(f"  ⊘ skipped  : {skipped}  (ALTER TABLE / CREATE DATABASE)")
    print(f"  ✗ errors   : {errors}")

    if failed_stmts:
        print("\nFailed statements:")
        for err, preview in failed_stmts[:20]:
            print(f"  [{err:.80}] {preview!r:.100}")

    # Sanity check — list tables and row counts
    con = sqlite3.connect(DB_PATH)
    tables = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print(f"\nTables in {DB_PATH.name} ({len(tables)} total):")
    for (name,) in tables:
        count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"  {name:<45} {count:>8} rows")
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
