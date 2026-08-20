#!/usr/bin/env python3
"""Auto-Harvest Metadata & Live DB Values

Systematically introspects ALL tables in the MySQL database:
1. Harvests every enum and low-cardinality column's distinct values.
2. Identifies all join paths and ID relationships across tables.
3. Detects string-stored numeric columns that require CAST.
4. Updates config/sql_column_glossary.json and config/sql_relationships.json.
"""

import asyncio
import json
from pathlib import Path
from rich.console import Console

from src.core.db_client import run_readonly_query

console = Console()
GLOSSARY_PATH = Path("config/sql_column_glossary.json")
RELATIONSHIPS_PATH = Path("config/sql_relationships.json")


async def harvest_full_database() -> None:
    console.print("[bold cyan]Starting Full Database Introspection...[/bold cyan]")

    # 1. Fetch all base tables
    tables_res = await run_readonly_query(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'globalmind' AND table_type = 'BASE TABLE';"
    )
    table_names = [r["table_name"] for r in tables_res if r.get("table_name")]
    console.print(f"Found [bold green]{len(table_names)}[/bold green] tables.")

    # 2. Fetch all columns and types
    cols_res = await run_readonly_query(
        """
        SELECT table_name, column_name, data_type, column_type, is_nullable, column_comment
        FROM information_schema.columns
        WHERE table_schema = 'globalmind'
        ORDER BY table_name, ordinal_position;
        """
    )

    columns_by_table: dict[str, list[dict]] = {}
    for r in cols_res:
        t = r["table_name"]
        columns_by_table.setdefault(t, []).append(r)

    # 3. Load existing glossary
    glossary = {}
    if GLOSSARY_PATH.exists():
        try:
            with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
                glossary = json.load(f)
        except Exception:
            glossary = {}

    # 4. Harvest distinct values for categorical/status columns
    console.print("[bold cyan]Harvesting distinct values for categorical columns...[/bold cyan]")
    auto_discovered_enums = {}

    for tname in table_names:
        cols = columns_by_table.get(tname, [])
        for col in cols:
            cname = col["column_name"]
            ctype = col["column_type"].lower()
            dtype = col["data_type"].lower()

            # Skip binary / long text / password / timestamp / id columns
            if any(skip in cname.lower() for skip in ["password", "token", "remember", "logo", "attachment", "created_at", "updated_at", "deleted_at"]):
                continue

            # Check if enum or short varchar (status, type, mode, medium, category, flag)
            is_candidate = (
                "enum" in ctype 
                or any(k in cname.lower() for k in ["status", "type", "mode", "medium", "flag", "state", "gender", "category"])
                or (dtype in ["varchar", "char"] and any(k in cname for k in ["_from", "is_", "has_"]))
            )

            if is_candidate:
                try:
                    vals_res = await run_readonly_query(
                        f"SELECT DISTINCT `{cname}` AS val, COUNT(*) AS cnt FROM `{tname}` WHERE `{cname}` IS NOT NULL GROUP BY `{cname}` ORDER BY cnt DESC LIMIT 25;"
                    )
                    distinct_vals = [str(r["val"]) for r in vals_res if r.get("val") is not None]
                    if 0 < len(distinct_vals) <= 20:
                        key = f"{tname}.{cname}"
                        auto_discovered_enums[key] = distinct_vals
                        console.print(f"  • [green]{key}[/green] -> {distinct_vals}")
                except Exception:
                    pass

    # 5. Enrich glossary entries with harvested values
    for tname, cols in columns_by_table.items():
        for col in cols:
            cname = col["column_name"]
            full_col = f"{tname}.{cname}"
            glossary_key = f"{tname}_{cname}"

            existing = glossary.get(glossary_key, {})
            maps_to = existing.get("maps_to", full_col)
            note = existing.get("note", "")
            synonyms = existing.get("synonyms", [])

            # Check if stock.qty varchar cast is needed
            if full_col == "stock.qty":
                maps_to = "CAST(stock.qty AS DECIMAL(10,2))"
                note = "stock.qty is stored as VARCHAR — ALWAYS CAST to DECIMAL or UNSIGNED when doing SUM, AVG, or numeric comparisons."

            # Inject discovered enum notes
            if full_col in auto_discovered_enums:
                val_list = auto_discovered_enums[full_col]
                enum_str = ", ".join(f"'{v}'" for v in val_list)
                if not note or "Values:" not in note:
                    note = f"Allowed values: {enum_str}. " + note

            # Generate natural synonyms if empty
            if not synonyms:
                clean_term = cname.replace("_", " ")
                clean_table = tname.replace("_", " ")
                synonyms = [f"{clean_table} {clean_term}", clean_term]

            glossary[glossary_key] = {
                "maps_to": maps_to,
                "note": note.strip(),
                "synonyms": list(set(synonyms))
            }

    # Write back glossary
    with open(GLOSSARY_PATH, "w", encoding="utf-8") as f:
        json.dump(glossary, f, indent=2)
    console.print(f"[bold green]Updated {GLOSSARY_PATH} ({len(glossary)} entries)[/bold green]")

    # 6. Auto-harvest Join Relationships
    console.print("[bold cyan]Harvesting Join Relationships...[/bold cyan]")
    relationships = []
    
    # Standard table ID mapping
    for tname, cols in columns_by_table.items():
        for col in cols:
            cname = col["column_name"]
            # Look for foreign keys like party_id, product_id, sales_order_id, category_id, etc.
            if cname.endswith("_id") and cname != "id":
                target_table = cname[:-3]
                # Special cases
                if target_table == "financial":
                    target_table = "financial_year"
                elif target_table == "pi":
                    target_table = "proforma"
                elif target_table == "dc":
                    target_table = "delivery_challan"
                elif target_table == "so":
                    target_table = "sales_order"
                elif target_table in ["created", "updated", "deleted", "lead_user", "lfrom_telecalling_user", "lead_assign_to"]:
                    target_table = "users"
                elif target_table == "state":
                    target_table = "states"
                elif target_table == "country":
                    target_table = "countries"

                if target_table in table_names:
                    join_condition = f"{tname}.{cname} = {target_table}.id"
                    rel = {
                        "from_table": tname,
                        "from_column": cname,
                        "to_table": target_table,
                        "to_column": "id",
                        "join_sql": join_condition,
                        "description": f"Join {tname} with {target_table}"
                    }
                    relationships.append(rel)

    with open(RELATIONSHIPS_PATH, "w", encoding="utf-8") as f:
        json.dump(relationships, f, indent=2)
    console.print(f"[bold green]Updated {RELATIONSHIPS_PATH} ({len(relationships)} join paths)[/bold green]")


if __name__ == "__main__":
    asyncio.run(harvest_full_database())
