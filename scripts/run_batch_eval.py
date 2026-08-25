#!/usr/bin/env python3
"""Batch Evaluation Benchmark Runner

Runs all 50 layman business questions through the Text-to-SQL pipeline:
- Validates SQL generation.
- Executes against the live MySQL database.
- Checks for syntax errors, zero-result traps, and execution time.
- Generates a full markdown report: evals/globalmind/eval_run_report.md.
"""

import asyncio
import re
import time
from pathlib import Path
from rich.console import Console
from rich.table import Table

from src.core.provider_client import ProviderRouter
from src.stages.s10_embeddings import EmbeddingService
from src.stages.s11_vector_store import QdrantStore
from src.stages.s12b_sql_retrieval import SQLRetriever

console = Console()
QUESTIONS_FILE = Path("evals/globalmind/reports/layman_questions_50.md")
REPORT_FILE = Path("evals/globalmind/reports/eval_run_report.md")


def extract_questions_from_md(md_path: Path) -> list[tuple[int, str, str]]:
    """Extract list of (q_num, question_text, business_goal) from markdown."""
    text = md_path.read_text(encoding="utf-8")
    pattern = re.compile(r'(\d+)\.\s+\*\*"([^"]+)"\*\*\s*\n\s+\*\s+\*Business Goal:\*\s+([^\n]+)')
    matches = pattern.findall(text)
    return [(int(m[0]), m[1], m[2]) for m in matches]


async def run_evaluation_suite(limit: int | None = None) -> None:
    questions = extract_questions_from_md(QUESTIONS_FILE)
    if limit:
        questions = questions[:limit]

    console.print(f"[bold cyan]Loaded {len(questions)} test questions from {QUESTIONS_FILE}[/bold cyan]")

    router = ProviderRouter()
    embed_svc = EmbeddingService()
    vector_store = QdrantStore()
    retriever = SQLRetriever(router, vector_store=vector_store, embedding_service=embed_svc)

    results = []
    summary = {"passed": 0, "empty": 0, "failed": 0, "total": len(questions)}

    table = Table(title="Batch Evaluation Progress")
    table.add_column("#", style="dim", width=4)
    table.add_column("Question", style="bold", width=40)
    table.add_column("Status", width=12)
    table.add_column("Time (s)", width=10)
    table.add_column("Rows / Notes", width=30)

    for q_num, q_text, goal in questions:
        start_t = time.monotonic()
        try:
            chunks = await retriever.retrieve(q_text)
            elapsed = round(time.monotonic() - start_t, 2)
            status = retriever.last_query_status or ("success" if chunks else "failed")
            
            sql_used = ""
            rows_preview = ""
            if chunks:
                content = chunks[0].chunk.content
                # Extract SQL
                sql_match = re.search(r"SQL Query Executed:\s*`([^`]+)`", content)
                sql_used = sql_match.group(1) if sql_match else ""
                rows_preview = content[:200].replace("\n", " ")

            if status == "success":
                summary["passed"] += 1
                status_badge = "[green]SUCCESS[/green]"
            elif status == "empty_result":
                summary["empty"] += 1
                status_badge = "[yellow]EMPTY[/yellow]"
            else:
                summary["failed"] += 1
                status_badge = "[red]FAILED[/red]"

            table.add_row(str(q_num), q_text[:38] + "...", status_badge, f"{elapsed}s", rows_preview[:28] + "...")
            results.append({
                "num": q_num,
                "question": q_text,
                "goal": goal,
                "status": status,
                "elapsed": elapsed,
                "cot_plan": retriever.last_cot_plan or "",
                "sql": sql_used,
                "preview": chunks[0].chunk.content if chunks else "No result",
            })
            
            # Pace requests
            await asyncio.sleep(1.0)

        except Exception as e:
            elapsed = round(time.monotonic() - start_t, 2)
            summary["failed"] += 1
            table.add_row(str(q_num), q_text[:38] + "...", "[red]ERROR[/red]", f"{elapsed}s", str(e)[:28])
            results.append({
                "num": q_num,
                "question": q_text,
                "goal": goal,
                "status": "error",
                "elapsed": elapsed,
                "cot_plan": "",
                "sql": "",
                "preview": f"Error: {e}",
            })

    console.print(table)
    console.print(f"\n[bold]Summary:[/bold] Passed: [green]{summary['passed']}[/green] | Empty: [yellow]{summary['empty']}[/yellow] | Failed: [red]{summary['failed']}[/red] / Total: {summary['total']}")

    # Write Markdown Report
    report_md = f"""# 📊 Full 50-Question Benchmark Evaluation Report

**Generated on:** {time.strftime('%Y-%m-%d %H:%M:%S')}  
**Total Questions Tested:** {summary['total']}  
**Success Rate:** {summary['passed']}/{summary['total']} ({(summary['passed'] + summary['empty']) / summary['total'] * 100:.1f}% valid SQL execution)  
- ✅ **Populated Results:** {summary['passed']}
- ⚠️ **Empty Results (Valid SQL, 0 records in DB):** {summary['empty']}
- ❌ **Failed:** {summary['failed']}

---

## 📋 Detailed Question Execution Matrix

| # | Question | Status | Time | Generated SQL | Result Summary |
|---|---|---|---|---|---|
"""
    for r in results:
        status_icon = "✅" if r["status"] == "success" else ("⚠️" if r["status"] == "empty_result" else "❌")
        clean_sql = f"`{r['sql']}`" if r['sql'] else "_None_"
        clean_preview = r['preview'].split("\n\n")[0].replace("\n", " ")[:120] if r['preview'] else ""
        report_md += f"| {r['num']} | **{r['question']}** | {status_icon} `{r['status']}` | {r['elapsed']}s | {clean_sql} | {clean_preview} |\n"

    report_md += "\n---\n\n## 📝 Full Per-Question Outputs & CoT Traces\n\n"
    for r in results:
        report_md += f"### Q{r['num']}: {r['question']}\n"
        report_md += f"- **Business Goal:** {r['goal']}\n"
        report_md += f"- **Status:** `{r['status']}` ({r['elapsed']}s)\n"
        if r.get('cot_plan'):
            report_md += f"#### 🧠 Chain-of-Thought Plan\n```text\n{r['cot_plan']}\n```\n\n"
        if r['sql']:
            report_md += f"#### 💻 Generated SQL\n```sql\n{r['sql']}\n```\n\n"
        report_md += f"**Output:**\n\n{r['preview']}\n\n---\n\n"

    REPORT_FILE.write_text(report_md, encoding="utf-8")
    console.print(f"[bold green]Report saved to {REPORT_FILE}[/bold green]")


if __name__ == "__main__":
    import sys
    limit_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_evaluation_suite(limit=limit_arg))
