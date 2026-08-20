#!/usr/bin/env python3
"""Interactive/CLI tool to test natural language questions against the live database.

Usage:
    .venv/bin/python scripts/test_question.py "Who bought the most goods from us this year?"
    .venv/bin/python scripts/test_question.py "How many active customers do we have?"
    .venv/bin/python scripts/test_question.py --sql "SELECT name, status FROM party LIMIT 5;"
"""

import argparse
import asyncio
import sys
from rich.console import Console
from rich.table import Table

from src.core.provider_client import ProviderRouter
from src.core.db_client import run_readonly_query
from src.stages.s12b_sql_retrieval import SQLRetriever, extract_analytical_intent

console = Console()


async def run_raw_sql(sql: str) -> None:
    """Execute raw SQL and print the results in a formatted table."""
    console.print(f"\n[bold cyan]Executing SQL:[/bold cyan]\n[green]{sql.strip()}[/green]\n")
    try:
        rows = await run_readonly_query(sql)
        if not rows:
            console.print("[yellow]0 records returned (Empty result).[/yellow]")
            return

        table = Table(title=f"Query Results ({len(rows)} rows)")
        for key in rows[0].keys():
            table.add_column(str(key), style="bold")

        for row in rows:
            table.add_row(*[str(val) if val is not None else "[dim]NULL[/dim]" for val in row.values()])

        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Database Error:[/bold red] {e}")


async def run_nl_question(question: str) -> None:
    """Convert natural language question to SQL via the pipeline and execute it."""
    console.print(f"\n[bold yellow]User Question:[/bold yellow] [bold white]\"{question}\"[/bold white]")
    
    # 1. Show Extracted Intent
    intent = extract_analytical_intent(question)
    console.print("\n[bold magenta]1. Extracted Analytical Intent:[/bold magenta]")
    for k, v in intent.items():
        if v:
            console.print(f"   • [bold]{k}:[/bold] {v}")

    # 2. Generate SQL
    console.print("\n[bold magenta]2. Generating SQL via LLM & Semantic Layer...[/bold magenta]")
    from src.stages.s10_embeddings import EmbeddingService
    from src.stages.s11_vector_store import QdrantStore

    router = ProviderRouter()
    embed_svc = EmbeddingService()
    vector_store = QdrantStore()
    retriever = SQLRetriever(router, vector_store=vector_store, embedding_service=embed_svc)

    chunks = await retriever.retrieve(question)

    if retriever.last_cot_plan:
        console.print("\n[bold cyan]🧠 Chain-of-Thought (CoT) Thinking Trace:[/bold cyan]")
        console.print(f"[dim]{retriever.last_cot_plan}[/dim]")

    if not chunks:
        console.print(f"\n[bold red]Status:[/bold red] {retriever.last_query_status} (No SQL generated or 0 records)")
        return

    chunk = chunks[0]
    console.print("\n[bold magenta]3. Formatted Result & SQL Query:[/bold magenta]")
    console.print(chunk.chunk.content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test NL2SQL and DB queries.")
    parser.add_argument("query", nargs="?", help="Natural language business question")
    parser.add_argument("--sql", help="Run a direct raw SQL statement")

    args = parser.parse_args()

    if args.sql:
        asyncio.run(run_raw_sql(args.sql))
    elif args.query:
        asyncio.run(run_nl_question(args.query))
    else:
        # Default demo query
        default_q = "Who bought the most goods from us this year?"
        console.print(f"[dim]No question provided. Running default demo: '{default_q}'[/dim]")
        asyncio.run(run_nl_question(default_q))


if __name__ == "__main__":
    main()
