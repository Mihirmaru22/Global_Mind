"""Stage 12b — Text-to-SQL Retrieval.

Dynamically translates natural language into SQL against the live database,
executes it, and returns the results formatted as a context chunk.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlglot import parse_one, exp

from src.core.db_client import run_readonly_query
from src.core.provider_client import ProviderRouter
from src.models.schemas import Chunk, ChunkType, RetrievedChunk, DocumentType

logger = logging.getLogger(__name__)

class UnsafeQueryError(Exception):
    """Raised when sqlglot rejects a query (e.g. not a SELECT). Never retried."""
    pass


class SQLRetriever:
    """Generates and executes SQL queries for analytical questions."""

    def __init__(self, router: ProviderRouter) -> None:
        self._router = router
        self._schema_cache: str | None = None

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
            # SQLite specific schema fetch
            rows = await run_readonly_query(
                "SELECT name, sql FROM sqlite_master WHERE type='table';"
            )
            schema_parts = []
            for row in rows:
                if row['name'] != 'sqlite_sequence':
                    schema_parts.append(row['sql'])
            
            self._schema_cache = "\\n\\n".join(schema_parts)
            return self._schema_cache
        except Exception as e:
            logger.error(f"Failed to fetch schema: {e}")
            return ""

    async def _generate_sql(self, query: str, schema: str, last_error: str | None = None) -> str:
        """Prompt the reasoning LLM to generate SQL."""
        system_prompt = f"""You are a SQLite expert. 
Given the following database schema, generate a highly optimized SQLite SELECT statement to answer the user's question.
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

    def _is_safe_read_query(self, sql: str) -> bool:
        """Use sqlglot to parse AST and ensure it's a single SELECT statement."""
        try:
            # Parse into AST (using sqlglot)
            ast = parse_one(sql, read="sqlite")
            
            # Must be a SELECT statement
            if not isinstance(ast, exp.Select):
                return False
                
            return True
        except Exception as e:
            logger.error(f"sqlglot rejected query '{sql}': {e}")
            return False

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
