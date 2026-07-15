"""Stage 12b — Text-to-SQL Retrieval.

Dynamically translates natural language into SQL against the live database,
executes it, and returns the results formatted as a context chunk.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlglot
from sqlglot import exp

from src.core.config import settings
from src.core.db_client import run_readonly_query
from src.core.provider_client import ProviderRouter
from src.core.sql_dialects import SQLDialectProfile, get_dialect_profile
from src.models.schemas import Chunk, ChunkType, RetrievedChunk, DocumentType

logger = logging.getLogger(__name__)


def format_schema_rows(profile: SQLDialectProfile, rows: list[dict[str, Any]]) -> str:
    """Turn an engine's raw introspection rows into schema text for the NL2SQL prompt.

    Pure function of (dialect profile, rows) — no instance state, no global
    settings — so it can be unit tested directly for each engine.

    SQLite's sqlite_master query already returns one full CREATE TABLE
    statement per row. MySQL's information_schema.columns query returns
    one row per column, so those need grouping by table first.
    """
    if profile.key == "sqlite":
        return "\n\n".join(
            row["sql"] for row in rows if row["name"] != "sqlite_sequence"
        )

    if profile.key == "mysql":
        tables: dict[str, list[str]] = {}
        for row in rows:
            tables.setdefault(row["table_name"], []).append(
                f"  {row['column_name']} {row['data_type']}"
            )
        return "\n\n".join(
            f"TABLE {name} (\n" + ",\n".join(cols) + "\n)"
            for name, cols in tables.items()
        )

    raise ValueError(f"Unsupported dialect key {profile.key!r}")

class UnsafeQueryError(Exception):
    """Raised when sqlglot rejects a query (e.g. not a SELECT). Never retried."""
    pass


class SQLRetriever:
    """Generates and executes SQL queries for analytical questions."""

    def __init__(self, router: ProviderRouter) -> None:
        self._router = router
        self._schema_cache: str | None = None
        self._dialect = get_dialect_profile(settings.db_engine)

    async def retrieve(self, query: str) -> list[RetrievedChunk]:
        """Convert NL to SQL, execute, and return formatted results (with 1 retry)."""
        schema = await self._get_schema()
        if not schema:
            return []

        last_error = None
        for attempt in range(2):
            sql = await self._generate_sql(query, schema, last_error)
            if not sql:
                return []

            try:
                # Validate safety (AST parsing)
                if not self._is_safe_read_query(sql):
                    raise UnsafeQueryError(f"Unsafe or unparseable SQL generated: {sql}")

                # Execute
                rows = await run_readonly_query(sql)
                
                if not rows:
                    return []
                    
                # Format to Markdown table
                formatted_table = self._format_rows_as_markdown(rows, sql)
                
                # Wrap in a RetrievedChunk
                chunk = Chunk(
                    chunk_id="live_sql_001",
                    document_id="live_db",
                    chunk_type=ChunkType.SQL_RESULT,
                    content=formatted_table,
                    document_type=DocumentType.GENERAL,
                    source_file="live_database (gpu_sales table)",
                )
                
                return [RetrievedChunk(chunk=chunk, score=1.0, retrieval_method="text-to-sql")]

            except UnsafeQueryError as e:
                # Security violations die instantly. No feedback loop.
                logger.warning(f"Blocked unsafe SQL query: {e}")
                return []
            except Exception as e:
                logger.error(f"SQL Execution failed on attempt {attempt + 1}: {e}")
                last_error = str(e)
                
        # If we exhausted retries, fail cleanly
        logger.warning("SQL generation failed after retry loop. Returning empty results.")
        return []

    async def _get_schema(self) -> str:
        """Fetch the DB schema (cached)."""
        if self._schema_cache:
            return self._schema_cache

        try:
            rows = await run_readonly_query(self._dialect.schema_query)
            self._schema_cache = format_schema_rows(self._dialect, rows)
            return self._schema_cache
        except Exception as e:
            logger.error(f"Failed to fetch schema: {e}")
            return ""

    async def _generate_sql(self, query: str, schema: str, last_error: str | None = None) -> str:
        """Prompt the reasoning LLM to generate SQL."""
        system_prompt = f"""You are a {self._dialect.name} expert. 
Given the following database schema, generate a highly optimized {self._dialect.name} SELECT statement to answer the user's question.
Return ONLY the raw SQL query, no markdown formatting, no explanations, no backticks.

Schema:
{schema}
"""
        if last_error:
            system_prompt += f"\n\nWARNING: Your previous attempt failed with this error: {last_error}\nPlease fix the SQL query and try again."
        
        try:
            response = await self._router.chat(
                task="reasoning",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                max_tokens=512
            )
            
            # Clean up markdown formatting if the LLM ignored instructions
            sql = response.strip()
            if sql.startswith("```sql"):
                sql = sql[6:]
            if sql.startswith("```"):
                sql = sql[3:]
            if sql.endswith("```"):
                sql = sql[:-3]
                
            return sql.strip()
        except Exception as e:
            logger.error(f"Failed to generate SQL: {e}")
            return ""

    # Functions that read/write files or execute code. Each is still a "SELECT"
    # to sqlglot, so isinstance(ast, exp.Select) alone would wave them through.
    _DANGEROUS_FUNCTIONS = frozenset({
        "load_file", "loadfile",              # MySQL: read an arbitrary file
        "sys_eval", "sys_exec", "sys_get",    # MySQL sys UDFs: shell execution
        "lo_import", "lo_export",             # Postgres large-object file I/O
    })

    def _is_safe_read_query(self, sql: str) -> bool:
        """Parse the AST and confirm it's a single, side-effect-free read SELECT.

        ``isinstance(ast, exp.Select)`` is necessary but NOT sufficient — several
        write/exfiltration primitives are still SELECTs:

          * ``SELECT ... INTO OUTFILE/DUMPFILE '/path'`` (MySQL) writes to disk;
          * ``SELECT LOAD_FILE('/etc/passwd')`` reads an arbitrary file;
          * a stacked ``SELECT 1; DROP TABLE t`` smuggles a second statement.

        This rejects all of the above so the generated query can only ever read
        rows, matching the layer's stated "read-only SELECT" guarantee.
        """
        try:
            # parse() (not parse_one) surfaces stacked statements so they can be
            # rejected rather than silently reduced to the first one.
            statements = [s for s in sqlglot.parse(sql, read=self._dialect.sqlglot_dialect) if s is not None]
        except Exception as e:
            logger.error(f"sqlglot rejected query '{sql}': {e}")
            return False

        if len(statements) != 1:
            logger.warning("Blocked multi-statement / stacked SQL: %s", sql)
            return False

        ast = statements[0]
        if not isinstance(ast, exp.Select):
            return False

        # SELECT ... INTO OUTFILE/DUMPFILE (or INTO @var) — a disk/variable write.
        if ast.args.get("into") is not None:
            logger.warning("Blocked SELECT ... INTO (file/variable write): %s", sql)
            return False

        # File-read / code-exec functions anywhere in the tree.
        for anon in ast.find_all(exp.Anonymous):
            fname = (anon.this or "")
            if isinstance(fname, str) and fname.lower() in self._DANGEROUS_FUNCTIONS:
                logger.warning("Blocked dangerous function '%s' in SQL: %s", fname, sql)
                return False

        return True

    def _format_rows_as_markdown(self, rows: list[dict[str, Any]], query: str) -> str:
        """Format dictionary rows into a markdown table."""
        if not rows:
            return "No results."
            
        headers = list(rows[0].keys())
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"
        
        table_rows = [f"SQL Query Executed: `{query}`\n", header_row, separator_row]
        
        for row in rows:
            values = [str(row[h]) for h in headers]
            table_rows.append("| " + " | ".join(values) + " |")
            
        return "\n".join(table_rows)
