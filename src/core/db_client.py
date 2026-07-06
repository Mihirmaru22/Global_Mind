"""Database Client — thin read-only adapter for live data retrieval."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite

from src.core.config import DATA_DIR

logger = logging.getLogger(__name__)

# Path to the local SQLite database
DB_PATH = DATA_DIR / "live_data.db"

# Safety limits
QUERY_TIMEOUT_SECONDS = 10.0
MAX_ROWS = 500


async def run_readonly_query(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Execute a read-only SQL query with hard timeouts and row caps.

    Args:
        sql: The SQL SELECT statement.
        params: Optional dictionary/tuple of parameters.

    Returns:
        List of rows as dictionaries.
        
    Raises:
        asyncio.TimeoutError: If the query exceeds the timeout limit.
        Exception: If the database throws a SQL error (e.g. syntax, missing table).
    """
    if not DB_PATH.exists():
        logger.warning(f"Database file not found at {DB_PATH}")
        return []

    import sqlglot
    from sqlglot import exp

    try:
        # Enforce hard row cap safely via AST
        tree = sqlglot.parse_one(sql, read="sqlite")
        
        # Only inject LIMIT for SELECT statements
        if isinstance(tree, exp.Select):
            existing = tree.args.get("limit")
            if existing is None:
                tree.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROWS)))
            else:
                try:
                    # If there's already a limit > MAX_ROWS, clamp it down
                    if int(existing.expression.this) > MAX_ROWS:
                        existing.set("expression", exp.Literal.number(MAX_ROWS))
                except (TypeError, ValueError, AttributeError):
                    pass
            
            # Serialize back to string without trailing semicolons
            sql = tree.sql(dialect="sqlite")
    except Exception as e:
        logger.error(f"Failed to parse SQL for limit enforcement: {e}")
        raise ValueError(f"Invalid SQL: {e}")

    try:
        async with asyncio.timeout(QUERY_TIMEOUT_SECONDS):
            # Enforce Layer 1 defense: SQLite engine-level Read-Only mode
            db_uri = f"file:{DB_PATH.resolve()}?mode=ro"
            async with aiosqlite.connect(db_uri, uri=True) as db:
                db.row_factory = aiosqlite.Row
                
                # Execute query
                async with db.execute(sql, params) as cursor:
                    rows = await cursor.fetchall()
                    
                    # Convert to list of dicts
                    results = [dict(row) for row in rows]
                    
                    if len(results) >= MAX_ROWS:
                        logger.warning(f"Query results capped at {MAX_ROWS} rows to protect context window.")
                        
                    return results

    except asyncio.TimeoutError:
        logger.error(f"SQL query timed out after {QUERY_TIMEOUT_SECONDS}s: {sql}")
        raise
    except Exception as e:
        logger.error(f"SQL execution failed: {e}")
        raise
