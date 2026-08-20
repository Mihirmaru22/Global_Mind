#!/usr/bin/env python3
"""High-Fidelity Behavioral Schema Atlas Generator.

Transforms the complete database schema, column glossary, and relational graph into
a rich cognitive Behavioral Schema Atlas (config/behavioral_schema_atlas.json)
codifying sparse tables, type casting rules, polymorphic disambiguation, enum translations,
and join warnings for all 64 tables.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT_DIR / "evals" / "globalmind" / "globalmind_schema.json"
GLOSSARY_PATH = ROOT_DIR / "config" / "sql_column_glossary.json"
RELS_PATH = ROOT_DIR / "config" / "sql_relationships.json"
OUTPUT_PATH = ROOT_DIR / "config" / "behavioral_schema_atlas.json"

# Domain Knowledge & Deep Architectural Rules Repository
TABLE_BEHAVIORAL_KNOWLEDGE = {
    "stock": {
        "meaning": "Physical on-hand inventory balances by product, color, and warehouse location.",
        "rules": [
            "SPARSE TABLE WARNING: This table is SPARSE. It only contains rows for items with >0 quantity (status = 'B'). Absence of a row means zero stock.",
            "To find zero-stock or low-stock items, you MUST start from the `product` table and use a LEFT JOIN to `stock`.",
            "MUST filter status = 'B' for on-hand available stock ('D' represents dispatched/historical rows).",
            "MUST always append `alias.deleted_at IS NULL` to exclude soft-deleted inventory.",
        ],
        "join_warnings": [
            "Never use an INNER JOIN on `stock` when querying for low stock or out-of-stock items; an INNER JOIN eliminates 0-stock products."
        ],
    },
    "sales_order": {
        "meaning": "Customer sales order headers recording order dates, customer references, and financial year links.",
        "rules": [
            "NON-EXISTENT COLUMN: `sales_order` has NO total amount column. You MUST calculate order totals by joining `sales_order_products` and `product` via SUM(sop.qty * p.rate).",
            "Customer Linkage: `party_id` links to `party.id`. Always join `party` to get `party.party_name`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause.",
            "For current financial year filtering, join `financial_year` and filter `financial_year.current_year = 'Y'`."
        ],
        "join_warnings": [
            "Do NOT attempt to SELECT total_amount, grand_total, or status from `sales_order` (they do not exist on this table)."
        ],
    },
    "sales_order_products": {
        "meaning": "Line-item product details for each sales order.",
        "rules": [
            "MUST use CAST(qty AS DECIMAL(10,2)) before ANY mathematical aggregation or comparison.",
            "Line Value Calculation: Calculate line total as `sop.qty * p.rate` by joining `product p ON sop.product_id = p.id`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "Always join `product` to retrieve item name and unit price (`product.rate`)."
        ],
    },
    "party": {
        "meaning": "Master entity directory holding both Customers and Suppliers.",
        "rules": [
            "POLYMORPHIC DISAMBIGUATION: `party` contains both Customers and Suppliers. Do not query this table in isolation.",
            "To find Customers: Disambiguate by joining to `sales_order` (`party.id = sales_order.party_id`).",
            "To find Suppliers/Vendors: Disambiguate by joining to `purchase` (`party.id = purchase.party_id`).",
            "Active Status Enum: `status = 'Y'` means Active, `status = 'N'` means Inactive.",
            "Customer/Supplier Name: Always select `party.party_name` (do NOT use `name` or `customer_name`).",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "Do NOT join to the `cities` table; the `cities` table is empty (0 rows). Query `party.city` directly as a text string."
        ],
    },
    "lead": {
        "meaning": "CRM prospective client inquiries, sales leads, and deal pipeline tracking.",
        "rules": [
            "Enum Translation: `status` allowed values are 'Pending', 'In-Progress', 'Success', 'Reject'.",
            "Sales Rep Allocation: Assigned sales representative is stored in `lead_assign_to`, which foreign-keys to `users.id` (`users.name`).",
            "Follow-up Medium Typo: Column is named `followup_medimum` (with an extra 'm'). Allowed values: 'Email', 'Call', 'PersonalMeeting', 'WhatsappMessage'.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "To get the sales rep name, join `users ON lead.lead_assign_to = users.id` (do not join `party`).",
            "Do NOT join to the `cities` table; query `lead.city` directly as a text string."
        ],
    },
    "lead_history": {
        "meaning": "CRM activity logs and interaction remarks for each lead.",
        "rules": [
            "Links to `lead` via `lead_id = lead.id`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    },
    "production": {
        "meaning": "Factory production planning orders specifying target quantities for machines and products.",
        "rules": [
            "Target vs Actual: `production.qty` represents the PLANNED TARGET quantity. Achieved output is stored in `actual_production.apq`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "To find production shortfalls or actual outputs, LEFT JOIN `actual_production` on `production.id = actual_production.production_id`."
        ]
    },
    "actual_production": {
        "meaning": "Actual completed factory floor manufacturing yields and batch outputs.",
        "rules": [
            "Actual Output Metric: `apq` represents Actual Production Quantity. Always use `SUM(apq)` to compute total manufactured yield.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "Join `production` on `actual_production.production_id = production.id` to access planned targets and machine assignments."
        ]
    },
    "machine": {
        "meaning": "Factory manufacturing machinery and assembly lines.",
        "rules": [
            "Machine Name: Stored in `machine_name`.",
            "Active Status Enum: `status = 'Y'` means Active/Operational, `status = 'N'` means Inactive.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    },
    "delivery_challan": {
        "meaning": "Outbound shipment dispatch notes and logistics manifests.",
        "rules": [
            "Logistics Details: Carrier is `transport_name`, driver is `driver_name`, vehicle is `vehicle_no`.",
            "Sales Order Linkage: Links to `sales_order` via `sales_order_id`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "Do NOT use `transporter_name` or `so_id`; use `transport_name` and `sales_order_id`."
        ]
    },
    "delivery_challan_products": {
        "meaning": "Individual line items and quantities shipped on a delivery challan.",
        "rules": [
            "Dispatched Quantity: Stored in `qty`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    },
    "proforma": {
        "meaning": "Proforma tax invoices recording billed amounts and GST collections.",
        "rules": [
            "NON-EXISTENT STATUS: `proforma` has NO `status` column. Do not filter by status on `proforma`.",
            "Total Invoiced Revenue: Stored in `grand_total`.",
            "Total Tax Amount: Stored in `gst_amount`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "Do NOT generate `WHERE proforma.status = ...`; no status column exists."
        ]
    },
    "quotation": {
        "meaning": "Sales price quotes provided to prospective or existing buyers.",
        "rules": [
            "NON-EXISTENT STATUS: `quotation` has NO `status` column. Do not filter by status on `quotation`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "Do NOT generate `WHERE quotation.status = ...`; no status column exists."
        ]
    },
    "purchase": {
        "meaning": "Procurement orders placed with external suppliers and material vendors.",
        "rules": [
            "NON-EXISTENT STATUS: `purchase` has NO `status` column. Do not filter by status on `purchase`.",
            "Supplier Linkage: Links to `party` via `party_id` where `party.profile_type = 'Party'`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": [
            "Do NOT generate `WHERE purchase.status = ...`; no status column exists."
        ]
    },
    "purchase_products": {
        "meaning": "Line items for material procurement orders.",
        "rules": [
            "Purchased Quantity: Stored in `qty`.",
            "Purchased Value Formula: Calculate as `SUM(pp.qty * p.rate)` by joining `product p ON pp.product_id = p.id`.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    },
    "financial_year": {
        "meaning": "Fiscal accounting year master records.",
        "rules": [
            "Current Year Enum: `current_year = 'Y'` identifies the active current financial year.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    },
    "product": {
        "meaning": "Master product SKU catalog.",
        "rules": [
            "Product Name: Stored in `product_name`.",
            "Unit Price: Stored in `rate`.",
            "Minimum Stock Threshold: Stored in `minimum_stock`.",
            "Finished Goods Enum: `product_type_id = 2` designates Finished Goods.",
            "Active Status Enum: `status = 'Y'` means Active, `status = 'N'` means Inactive.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    },
    "product_color": {
        "meaning": "Color variants and SKUs for products.",
        "rules": [
            "Variant Name: Stored in `color_name`.",
            "Product Linkage: `product_id` links to `product.id`."
        ],
        "join_warnings": []
    },
    "category": {
        "meaning": "Product category taxonomy.",
        "rules": [
            "Category Name: Stored in `category_name`.",
            "Active Status Enum: `status = 'Y'` means Active, `status = 'N'` means Inactive.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    },
    "users": {
        "meaning": "System users, sales representatives, and staff members.",
        "rules": [
            "Staff Name: Stored in `name`.",
            "Active Status Enum: `status = 'Y'` means Active, `status = 'N'` means Inactive.",
            "MUST always append `alias.deleted_at IS NULL` in WHERE clause."
        ],
        "join_warnings": []
    }
}

# Column-Specific Behavioral Knowledge
COLUMN_BEHAVIORAL_KNOWLEDGE = {
    "stock.qty": {
        "meaning": "Quantity of product units in stock.",
        "rules": [
            "MUST use CAST(qty AS DECIMAL(10,2)) before ANY aggregation (SUM, AVG) or mathematical comparison.",
            "Stock rows represent positive balances; use COALESCE(SUM(CAST(qty AS DECIMAL(10,2))), 0) when LEFT JOINing."
        ],
        "warnings": ["Stored as VARCHAR(50) in MySQL; never aggregate directly without CAST."],
        "formula": "COALESCE(SUM(CAST(stock.qty AS DECIMAL(10,2))), 0)"
    },
    "stock.status": {
        "meaning": "Physical disposition status of inventory row.",
        "rules": [
            "Enum Translation: 'B' means Booked / Available On-Hand Stock.",
            "Enum Translation: 'D' means Dispatched / Shipped Stock.",
            "For available warehouse inventory, MUST filter `stock.status = 'B'`."
        ],
        "warnings": [],
        "formula": None
    },
    "stock.carton_verify_status": {
        "meaning": "Warehouse physical audit and verification state of carton box.",
        "rules": [
            "Enum Translation: 'P' means Pending / Unverified Carton.",
            "Enum Translation: 'V' means Verified Carton."
        ],
        "warnings": [],
        "formula": None
    },
    "party.party_name": {
        "meaning": "Official registered business or individual name of customer or vendor.",
        "rules": [
            "Always select `party_name` for customer or supplier names.",
            "Never use `name` or `customer_name` on table `party`."
        ],
        "warnings": [],
        "formula": None
    },
    "party.status": {
        "meaning": "Active/Inactive account status flag.",
        "rules": [
            "Enum Translation: 'Y' means Active Account.",
            "Enum Translation: 'N' means Inactive / Suspended Account."
        ],
        "warnings": [],
        "formula": None
    },
    "party.city": {
        "meaning": "City name stored directly as string.",
        "rules": [
            "Query city directly as text on `party.city`.",
            "Do NOT join `cities` table; `cities` is empty (0 rows)."
        ],
        "warnings": ["Do NOT join to cities table."],
        "formula": None
    },
    "sales_order_products.qty": {
        "meaning": "Ordered quantity of product units on sales order.",
        "rules": [
            "MUST use CAST(qty AS DECIMAL(10,2)) or numeric arithmetic before aggregation.",
            "Calculate sales order revenue as SUM(sop.qty * p.rate)."
        ],
        "warnings": [],
        "formula": "SUM(sop.qty * prod.rate)"
    },
    "purchase_products.qty": {
        "meaning": "Purchased quantity of material on purchase order.",
        "rules": [
            "Calculate purchase expenditure as SUM(pp.qty * p.rate)."
        ],
        "warnings": [],
        "formula": "SUM(pp.qty * prod.rate)"
    },
    "actual_production.apq": {
        "meaning": "Actual Production Quantity achieved on factory floor.",
        "rules": [
            "Actual output metric; use SUM(apq) for completed manufacturing yield."
        ],
        "warnings": [],
        "formula": "SUM(actual_production.apq)"
    },
    "production.qty": {
        "meaning": "Planned production target quantity.",
        "rules": [
            "Represents planned target; compare against actual_production.apq to compute shortfalls."
        ],
        "warnings": [],
        "formula": "SUM(production.qty)"
    },
    "lead.status": {
        "meaning": "CRM prospective inquiry conversion pipeline stage.",
        "rules": [
            "Enum Translation: 'Pending' means Open New Inquiry awaiting action.",
            "Enum Translation: 'In-Progress' means Active Negotiation in pipeline.",
            "Enum Translation: 'Success' means Won / Converted to Customer.",
            "Enum Translation: 'Reject' means Lost / Rejected Inquiry."
        ],
        "warnings": [],
        "formula": None
    },
    "lead.lead_assign_to": {
        "meaning": "Foreign key reference to assigned sales representative user.",
        "rules": [
            "Join `users` via `lead.lead_assign_to = users.id` to get sales rep name (`users.name`)."
        ],
        "warnings": ["Do not join party for sales reps; join users."],
        "formula": None
    },
    "lead.followup_medimum": {
        "meaning": "Communication channel medium for client followups.",
        "rules": [
            "Typo Note: Column is spelled `followup_medimum` with extra 'm'.",
            "Enum Translation: 'Email', 'Call', 'PersonalMeeting', 'WhatsappMessage'."
        ],
        "warnings": ["Column name in database is followup_medimum (not followup_medium)."],
        "formula": None
    },
    "financial_year.current_year": {
        "meaning": "Active financial year indicator flag.",
        "rules": [
            "Enum Translation: 'Y' means Current Active Financial Year.",
            "Enum Translation: 'N' means Past / Historical Financial Year."
        ],
        "warnings": [],
        "formula": None
    },
    "proforma.grand_total": {
        "meaning": "Total invoiced gross billing amount including GST and discounts.",
        "rules": [
            "Use SUM(grand_total) for total invoiced revenue or net billed sales."
        ],
        "warnings": [],
        "formula": "SUM(proforma.grand_total)"
    },
    "proforma.gst_amount": {
        "meaning": "Total GST tax amount collected on proforma invoices.",
        "rules": [
            "Use SUM(gst_amount) for total collected GST tax liability."
        ],
        "warnings": [],
        "formula": "SUM(proforma.gst_amount)"
    }
}


def build_behavioral_atlas() -> Dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_data = json.load(f)

    glossary = {}
    if GLOSSARY_PATH.exists():
        with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
            glossary = json.load(f)

    tables_list = schema_data.get("tables", [])
    relationships_list = schema_data.get("relationships", [])

    atlas: Dict[str, Any] = {
        "_metadata": {
            "version": "2.0.0",
            "title": "GlobalMind Behavioral Schema Atlas & Cognitive Ontology",
            "database": schema_data.get("database", "globalmind"),
            "table_count": len(tables_list),
            "generated_at": "2026-08-19",
        },
        "tables": {},
    }

    for t in tables_list:
        t_name = t.get("name", "")
        t_domain = t.get("domain", "General")
        cols = t.get("columns", [])
        has_deleted_at = any(c.get("name") == "deleted_at" for c in cols)

        # Get curated or baseline table knowledge
        t_know = TABLE_BEHAVIORAL_KNOWLEDGE.get(t_name, {})
        t_meaning = t_know.get("meaning", f"{t_name.replace('_', ' ').title()} operational records in {t_domain}.")
        t_rules = list(t_know.get("rules", []))
        if has_deleted_at and not any("deleted_at" in r for r in t_rules):
            t_rules.append(f"MUST always append `{t_name}.deleted_at IS NULL` in the WHERE clause.")

        t_join_warnings = list(t_know.get("join_warnings", []))

        table_entry = {
            "table_name": t_name,
            "domain": t_domain,
            "table_meaning": t_meaning,
            "table_behavioral_rules": t_rules,
            "join_warnings": t_join_warnings,
            "columns": {},
        }

        for col in cols:
            c_name = col.get("name", "")
            c_type = col.get("type", "VARCHAR")
            full_col_key = f"{t_name}.{c_name}"

            col_know = COLUMN_BEHAVIORAL_KNOWLEDGE.get(full_col_key, {})
            gloss_entry = glossary.get(full_col_key, {})

            c_meaning = col_know.get("meaning") or gloss_entry.get("note") or f"{c_name.replace('_', ' ').title()} attribute of {t_name}."
            c_rules = list(col_know.get("rules", []))

            # Auto-codify allowed values / enums if available
            allowed_vals = gloss_entry.get("allowed_values")
            if allowed_vals and not any("Enum Translation" in r for r in c_rules):
                if isinstance(allowed_vals, dict):
                    enum_str = ", ".join(f"'{k}' means {v}" for k, v in allowed_vals.items())
                    c_rules.append(f"Enum Translation: {enum_str}.")
                elif isinstance(allowed_vals, list):
                    enum_str = ", ".join(f"'{v}'" for v in allowed_vals)
                    c_rules.append(f"Allowed Values: {enum_str}.")

            c_warnings = list(col_know.get("warnings", []))
            c_formula = col_know.get("formula") or gloss_entry.get("maps_to", None)

            table_entry["columns"][c_name] = {
                "type": c_type,
                "business_meaning": c_meaning,
                "behavioral_rules": c_rules,
                "join_warnings": c_warnings,
                "aggregation_formula": c_formula,
            }

        atlas["tables"][t_name] = table_entry

    return atlas


def main():
    atlas = build_behavioral_atlas()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(atlas, f, indent=2)

    print(f"✅ Generated Behavioral Schema Atlas with {len(atlas['tables'])} tables at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
