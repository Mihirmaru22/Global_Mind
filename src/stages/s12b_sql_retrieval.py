"""Stage 12b — Text-to-SQL Retrieval.

Dynamically translates natural language into SQL against the live database,
executes it, and returns the results formatted as a context chunk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
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
            comment = row.get("column_comment") or ""
            suffix = f"  -- {comment}" if comment else ""
            tables.setdefault(row["table_name"], []).append(
                f"  {row['column_name']} {row['data_type']}{suffix}"
            )
        return "\n\n".join(
            f"TABLE {name} (\n" + ",\n".join(cols) + "\n)"
            for name, cols in tables.items()
        )

    raise ValueError(f"Unsupported dialect key {profile.key!r}")


def format_fk_rows(rows: list[dict]) -> str:
    if not rows:
        return ""

    lines = [
        f"  {r['table_name']}.{r['column_name']} -> {r['referenced_table_name']}.{r['referenced_column_name']}"
        for r in rows
    ]
    return "Foreign Keys:\n" + "\n".join(lines)


class UnsafeQueryError(Exception):
    """Raised when sqlglot rejects a query (e.g. not a SELECT). Never retried."""
    pass


def _extract_table_names(sql: str, dialect: str) -> list[str]:
    try:
        ast = sqlglot.parse_one(sql, read=dialect)
        return sorted({t.name for t in ast.find_all(exp.Table)})
    except Exception:
        return []


class SQLRetriever:
    """Generates and executes SQL queries for analytical questions."""

    def __init__(self, router: ProviderRouter) -> None:
        self._router = router
        self._schema_cache: str | None = None
        self._dialect = get_dialect_profile(settings.db_engine)
        self._glossary = self._load_glossary()

    @staticmethod
    def _load_glossary() -> str:
        path = Path(__file__).resolve().parents[2] / "config" / "sql_glossary.json"
        try:
            groups = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(groups, dict) or not groups:
                return ""

            lines: list[str] = []
            for concept, syns in groups.items():
                if isinstance(syns, str):
                    synonym_text = syns
                elif isinstance(syns, list):
                    synonym_text = ", ".join(str(item) for item in syns if str(item).strip())
                else:
                    synonym_text = str(syns)

                synonym_text = synonym_text.strip()
                if synonym_text:
                    lines.append(f"- {concept}: {synonym_text}")
            return "\n".join(lines)
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            return ""

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

                # An empty result is ambiguous: it can mean the query is correct
                # and the true answer is "none", or that a wrong JOIN/WHERE
                # silently matched nothing (MySQL doesn't error on that, it just
                # returns 0 rows). Give the model one retry with that context on
                # the first attempt. On the final attempt, trust the result and
                # return it as a legitimate zero-row answer instead of silently
                # falling back to document search.
                if not rows and attempt == 0:
                    last_error = (
                        "Query executed successfully but returned 0 rows. If that's "
                        "surprising given the question, double-check your JOIN "
                        "conditions reference the correct foreign key columns."
                    )
                    continue

                tables = _extract_table_names(sql, self._dialect.sqlglot_dialect)
                label = f"live_database ({', '.join(tables)})" if tables else "live_database"

                # Format to Markdown table
                formatted_table = (
                    self._format_rows_as_markdown(rows, sql)
                    if rows
                    else "Query executed successfully — no matching records were found."
                )
                
                # Wrap in a RetrievedChunk
                chunk = Chunk(
                    chunk_id="live_sql_001",
                    document_id="live_db",
                    chunk_type=ChunkType.SQL_RESULT,
                    content=formatted_table,
                    document_type=DocumentType.GENERAL,
                    source_file=label,
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
            schema = format_schema_rows(self._dialect, rows)

            if self._dialect.key == "mysql" and self._dialect.fk_query:
                fk_rows = await run_readonly_query(self._dialect.fk_query)
            elif self._dialect.key == "sqlite":
                fk_rows = await self._fetch_sqlite_foreign_keys()
            else:
                fk_rows = []

            fk_text = format_fk_rows(fk_rows)
            schema = schema + ("\n\n" + fk_text if fk_text else "")

            self._schema_cache = schema
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
        system_prompt += self._OUTPUT_READABILITY_RULES

        if self._glossary:
            system_prompt += (
                "\n\nBusiness term glossary (user may use these informal terms):\n"
                f"{self._glossary}"
            )
        if self._dialect.date_functions:
            system_prompt += (
                f"\n\nDate/time syntax for {self._dialect.name} "
                "(use these exact forms for relative dates like 'last month', 'this year'):\n"
                f"{self._dialect.date_functions}"
            )
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

    _OUTPUT_READABILITY_RULES = """
Output readability rules:
- Never return a raw ID column (e.g. customer_id, product_id, order_id) by itself if a related table has a human-readable name, title, or label for it. JOIN to that table and return the readable value instead of, or alongside, the ID.
- Give every selected column a clear, descriptive alias using AS, so the result is understandable on its own without needing to see the query (e.g. SELECT c.name AS customer_name, SUM(o.amount) AS total_revenue — not SELECT c.name, SUM(o.amount)).
- Name each alias based on what the user actually asked for, not the raw column or table name (e.g. if the user asked "who spent the most", alias the result as top_customer or total_spent, not c1 or col2).
- Include any extra column that adds useful context to the answer (name, category, date, status) even if not strictly required to answer narrowly — the goal is a result a person can read and understand directly, not just the minimum data needed.
"""

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

    async def _fetch_sqlite_foreign_keys(self) -> list[dict]:
        tables = await run_readonly_query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence';"
        )
        fks = []
        for row in tables:
            table = row["name"]
            escaped_table = table.replace('"', '""')
            cols = await run_readonly_query(f'PRAGMA foreign_key_list("{escaped_table}");')
            for c in cols:
                fks.append({
                    "table_name": table,
                    "column_name": c["from"],
                    "referenced_table_name": c["table"],
                    "referenced_column_name": c["to"],
                })
        return fks

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
