"""SQL dialect facts for the Text-to-SQL retrieval layer.

This intentionally stays data, not an interface: SQLite and MySQL differ mainly
in three facts (what to call the dialect in the NL2SQL prompt, which sqlglot
dialect to parse/serialize with, and how to introspect the schema). Adding a
new engine means adding one entry here.

Connection handling is NOT unified here — the aiosqlite/aiomysql driver APIs
differ enough (context-managed connection vs. explicit cursor) that forcing a
shared interface would just be boilerplate around a branch. That branch lives
directly in db_client.py, where it's one `if` on `settings.db_engine`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SQLDialectProfile:
    """Facts about one SQL engine, used to drive prompting, parsing, and introspection."""

    key: str
    """Registry key for this profile (matches settings.db_engine values, e.g. "mysql")."""

    name: str
    """Human-readable name interpolated into the NL2SQL system prompt (e.g. "MySQL expert")."""

    sqlglot_dialect: str
    """Dialect string passed to sqlglot.parse_one()/tree.sql() for parsing and re-serialization."""

    schema_query: str
    """Read-only query used to introspect available tables/columns for this engine."""


DIALECTS: dict[str, SQLDialectProfile] = {
    "sqlite": SQLDialectProfile(
        key="sqlite",
        name="SQLite",
        sqlglot_dialect="sqlite",
        schema_query="SELECT name, sql FROM sqlite_master WHERE type='table';",
    ),
    "mysql": SQLDialectProfile(
        key="mysql",
        name="MySQL",
        sqlglot_dialect="mysql",
        schema_query="""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
            ORDER BY table_name, ordinal_position;
        """,
    ),
    # SQL Server, if/when needed: add an entry here (sqlglot_dialect="tsql",
    # schema_query against INFORMATION_SCHEMA.COLUMNS or sys.columns). Not
    # added speculatively — there's no instance to validate the LIMIT->TOP
    # transpilation or a read-only login against yet.
}


def get_dialect_profile(engine: str) -> SQLDialectProfile:
    """Look up the dialect profile for the configured engine.

    Raises:
        ValueError: If the engine isn't in DIALECTS (fails fast at startup-adjacent
            code paths rather than producing confusing downstream sqlglot errors).
    """
    try:
        return DIALECTS[engine]
    except KeyError:
        raise ValueError(
            f"Unsupported db_engine {engine!r}. Supported engines: {list(DIALECTS)}"
        ) from None
