#!/usr/bin/env python3
"""Option A: Behavioral Schema Atlas Generator.

Reads the complete database schema and column metadata, prompts the LLM with deep
architectural and behavioral instructions, and creates `config/behavioral_schema_atlas.json`.

Usage:
    .venv/bin/python scripts/generate_behavioral_atlas.py
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from src.core.provider_client import ProviderRouter

console = Console()

ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_SCHEMA_PATH = ROOT_DIR / "evals" / "globalmind" / "globalmind_schema.json"
INPUT_GLOSSARY_PATH = ROOT_DIR / "config" / "sql_column_glossary.json"
OUTPUT_ATLAS_PATH = ROOT_DIR / "config" / "behavioral_schema_atlas.json"

MASTER_PROMPT_TEMPLATE = """You are a Senior Enterprise Database Architect and Data Ontologist. 
Your task is to transform a database table schema and column glossary into a rich "Behavioral Schema Atlas" entry for MySQL.

Table Name: {table_name}
Table Domain: {table_domain}
Columns & Metadata:
{columns_json}

Relevant Known Relationships:
{relationships_json}

For this table and its critical columns, you must generate a JSON object with:
1. "table_meaning": A 1-2 sentence plain-English explanation of what this table represents in business operations.
2. "table_behavioral_rules": An array of strict, actionable rules for this table:
   - SPARSE TABLE WARNINGS: If this table only contains rows for active/positive states (e.g. stock > 0), explicitly state: "This table is sparse. Absence of a row means zero/null. You MUST use a LEFT JOIN from the parent table to find missing/zero items."
   - SOFT DELETE ENFORCEMENT: If the table has a `deleted_at` column, state: "MUST always append `alias.deleted_at IS NULL` in the WHERE clause."
   - POLYMORPHIC DISAMBIGUATION: If this table serves multiple roles (e.g. `party` is both Customer and Supplier), state: "Disambiguate by joining to `sales_order` for Customers or `purchase` for Suppliers."
   - NON-EXISTENT COLUMNS: If this table lacks expected columns (e.g. `quotation`, `proforma`, `purchase` have NO status column; `sales_order` has NO total amount column), explicitly warn against filtering by them.
3. "columns": A dictionary keyed by column name, where each column has:
   - "type": SQL data type (e.g. "VARCHAR(50)", "INT", "DECIMAL(10,2)").
   - "business_meaning": 1 sentence explanation of what this column represents.
   - "behavioral_rules": Array of actionable rules (e.g. "MUST use CAST(qty AS DECIMAL(10,2)) before ANY aggregation or comparison", "Enum Translation: 'B' means Booked/On-Hand Available, 'D' means Dispatched/Shipped", "'P' means Pending, 'V' means Verified", "'Y' means Active, 'N' means Inactive").
   - "join_warnings": Warnings about common traps (e.g. "Do not join to `cities` table; it is empty. Use `city` directly as string.").
   - "aggregation_formula": SQL formula if part of a computed metric (e.g. "SUM(sop.qty * p.rate)", "COALESCE(SUM(CAST(s.qty AS DECIMAL(10,2))), 0)", or null).

CRITICAL CONSTRAINTS:
- Be highly specific to MySQL syntax.
- Do not invent columns that are not in the provided input.
- Output ONLY valid, parseable JSON matching the following structure:
{{
  "table_name": "{table_name}",
  "table_meaning": "...",
  "table_behavioral_rules": [...],
  "columns": {{
    "column_name": {{
      "type": "...",
      "business_meaning": "...",
      "behavioral_rules": [...],
      "join_warnings": [...],
      "aggregation_formula": "..."
    }}
  }}
}}
Do NOT include markdown formatting or explanations outside the JSON block.
"""


def _clean_json_response(raw_text: str) -> Dict[str, Any]:
    """Strip markdown code fences and extract valid JSON."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    # Locate first '{' and last '}'
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    
    return json.loads(text)


async def enrich_table(
    router: ProviderRouter,
    table_name: str,
    table_domain: str,
    columns: List[Dict[str, Any]],
    relationships: List[Dict[str, Any]],
    glossary: Dict[str, Any],
) -> Dict[str, Any]:
    """Enrich a single table schema with behavioral rules via LLM."""
    # Filter glossary for columns belonging to this table
    cols_meta = []
    for col in columns:
        c_name = col.get("name", "")
        c_type = col.get("type", "")
        c_key = f"{table_name}.{c_name}"
        glossary_entry = glossary.get(c_key, {})
        cols_meta.append({
            "name": c_name,
            "type": c_type,
            "nullable": col.get("nullable", True),
            "glossary_note": glossary_entry.get("note", ""),
            "allowed_values": glossary_entry.get("allowed_values", None),
        })

    prompt = MASTER_PROMPT_TEMPLATE.format(
        table_name=table_name,
        table_domain=table_domain,
        columns_json=json.dumps(cols_meta, indent=2),
        relationships_json=json.dumps(relationships, indent=2),
    )

    for attempt in range(3):
        try:
            response = await router.chat(
                task="reasoning",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            data = _clean_json_response(response)
            return data
        except Exception as e:
            if attempt == 2:
                console.print(f"[bold red]❌ Failed to enrich {table_name}:[/bold red] {e}")
                # Return basic fallback
                return {
                    "table_name": table_name,
                    "table_meaning": f"Table for {table_name} in domain {table_domain}.",
                    "table_behavioral_rules": ["MUST filter deleted_at IS NULL if column exists."],
                    "columns": {
                        c["name"]: {
                            "type": c["type"],
                            "business_meaning": f"Column {c['name']} of {table_name}.",
                            "behavioral_rules": [],
                            "join_warnings": [],
                            "aggregation_formula": None,
                        }
                        for c in cols_meta
                    },
                }
            await asyncio.sleep(2.0 * (attempt + 1))


async def main():
    parser = argparse.ArgumentParser(description="Generate Behavioral Schema Atlas")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of tables to process (for testing)")
    args = parser.parse_args()

    console.print("\n[bold cyan]🚀 Starting Behavioral Schema Atlas Generation...[/bold cyan]\n")

    if not INPUT_SCHEMA_PATH.exists():
        console.print(f"[bold red]❌ Input schema file not found:[/bold red] {INPUT_SCHEMA_PATH}")
        return

    with open(INPUT_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_data = json.load(f)

    glossary = {}
    if INPUT_GLOSSARY_PATH.exists():
        with open(INPUT_GLOSSARY_PATH, "r", encoding="utf-8") as f:
            glossary = json.load(f)

    tables_list = schema_data.get("tables", [])
    relationships_list = schema_data.get("relationships", [])

    # Filter out system/temp views if any
    filtered_tables = [
        t for t in tables_list 
        if not t.get("is_view", False) 
        and not t.get("name", "").startswith("temp")
        and not t.get("name", "").startswith("test")
    ]

    if args.limit:
        filtered_tables = filtered_tables[: args.limit]

    console.print(f"📊 Found [bold green]{len(filtered_tables)}[/bold green] tables to enrich into the Atlas.\n")

    router = ProviderRouter()
    atlas: Dict[str, Any] = {
        "_metadata": {
            "version": "2.0.0",
            "generated_at": "2026-08-19",
            "database": schema_data.get("database", "globalmind"),
            "table_count": len(filtered_tables),
        },
        "tables": {},
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Enriching tables...", total=len(filtered_tables))

        for t_info in filtered_tables:
            t_name = t_info.get("name", "")
            t_domain = t_info.get("domain", "General")
            t_cols = t_info.get("columns", [])
            
            # Find relationships involving this table
            t_rels = [
                r for r in relationships_list
                if r.get("from_table") == t_name or r.get("to_table") == t_name
            ]

            progress.update(task, description=f"[cyan]Enriching {t_name} ({t_domain})...")
            enriched = await enrich_table(
                router=router,
                table_name=t_name,
                table_domain=t_domain,
                columns=t_cols,
                relationships=t_rels,
                glossary=glossary,
            )
            atlas["tables"][t_name] = enriched
            progress.advance(task)
            
            # Pacing delay to respect API limits
            await asyncio.sleep(2.5)

    OUTPUT_ATLAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_ATLAS_PATH, "w", encoding="utf-8") as f:
        json.dump(atlas, f, indent=2)

    console.print(f"\n[bold green]✅ Successfully generated Behavioral Schema Atlas at:[/bold green] [underline]{OUTPUT_ATLAS_PATH}[/underline]\n")


if __name__ == "__main__":
    asyncio.run(main())
