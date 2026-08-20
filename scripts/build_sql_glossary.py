#!/usr/bin/env python3
"""Build a schema-aware column glossary for Text-to-SQL.

Reads the existing config/sql_glossary.json (business terms) and
evals/globalmind/globalmind_schema.json (schema), and produces a new
config/sql_column_glossary.json mapping business terms to exact table.column paths.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent.resolve()
REPO = HERE.parent
SCHEMA_FILE = REPO / "evals" / "globalmind" / "globalmind_schema.json"
OLD_GLOSSARY_FILE = REPO / "config" / "sql_glossary.json"
OUT_FILE = REPO / "config" / "sql_column_glossary.json"

# Manual overrides for terms that need complex logic, CASTs, or business definitions.
OVERRIDES = {
    "revenue": {
        "maps_to": "SUM(product.rate * sales_order_products.qty)",
        "note": "Booked base sales value (excluding tax) from sales orders. If question specifically asks for invoiced/tax-inclusive revenue or billing, use proforma.grand_total.",
        "synonyms": ["total sales", "sales value", "turnover", "sales amount", "base sales", "money made"],
    },
    "invoiced_revenue": {
        "maps_to": "SUM(proforma.grand_total)",
        "note": "Invoiced total amount including GST and discounts from proforma invoices.",
        "synonyms": ["invoiced total", "billed amount", "invoice revenue", "grand total", "net billing", "billed sales"],
    },
    "tax_amount": {
        "maps_to": "SUM(proforma.gst_amount)",
        "note": "Total GST tax amount from proforma invoices.",
        "synonyms": ["gst amount", "tax collected", "total gst", "tax value", "gst total"],
    },
    "stock_quantity": {
        "maps_to": "CAST(stock.qty AS UNSIGNED)",
        "note": "stock.qty is VARCHAR — CAST before aggregating.",
        "synonyms": ["inventory", "on-hand", "stock level", "available quantity", "stock on hand"],
    },
    "customer": {
        "maps_to": "party.party_name",
        "note": "party table holds both customers (profile_type='Party') and suppliers (profile_type='Company').",
        "synonyms": ["client", "buyer", "account", "customer name", "purchaser"],
    },
    "dispatched_quantity": {
        "maps_to": "delivery_challan_products.qty",
        "note": "Quantity dispatched via delivery challans.",
        "synonyms": ["dispatched", "shipped", "sent out", "delivery quantity", "dispatch count"],
    },
    "packed_cartons": {
        "maps_to": "packagings.packing_qty_count",
        "note": "Verified packed carton count (carton_verify_status='V').",
        "synonyms": ["cartons", "packed boxes", "ready cartons", "boxed stock", "warehouse boxes"],
    },
    "quotation": {
        "maps_to": "SUM(quotation_products.final_amount)",
        "note": "Price estimates, proposals, and quotations sent to customers.",
        "synonyms": ["quote", "estimate", "proposal", "price estimate", "quotations", "estimates", "proposals", "price estimates"],
    },
    "vendor": {
        "maps_to": "party.party_name",
        "note": "Suppliers and raw material vendors (party.profile_type='Company').",
        "synonyms": ["supplier", "seller", "raw material vendor", "suppliers", "vendors", "sellers"],
    },
    "purchase_quantity": {
        "maps_to": "purchase_products.qty",
        "note": "Quantity of raw materials or stock purchased from suppliers.",
        "synonyms": ["supplies bought", "materials purchased", "procured items", "purchase qty", "bought quantity"],
    },
    "transporter": {
        "maps_to": "delivery_challan.transport_name",
        "note": "Logistics carrier or transport company used for dispatch.",
        "synonyms": ["logistics company", "carrier", "shipping company", "transport agency", "logistics partner"],
    },
    "lead_inquiry": {
        "maps_to": "lead.company_name",
        "note": "Sales inquiries and potential client leads.",
        "synonyms": ["sales lead", "inquiry", "prospect", "new inquiry", "business lead", "leads", "inquiries", "prospects"],
    },
    "opening_balance": {
        "maps_to": "party_opening_balance.opening_balance",
        "note": "Initial starting balance for customers or suppliers.",
        "synonyms": ["initial balance", "starting balance", "opening dues", "prior balance", "carried forward balance"],
    },
    "stock_adjustment": {
        "maps_to": "stock_adjustment.qty",
        "note": "Manual inventory corrections and adjustments.",
        "synonyms": ["inventory correction", "stock write-off", "manual adjustment", "stock correction", "reconciled quantity"],
    },
}


def build_glossary() -> None:
    print(f"Reading schema from {SCHEMA_FILE}")
    schema_data = json.loads(SCHEMA_FILE.read_text())

    print(f"Reading base glossary from {OLD_GLOSSARY_FILE}")
    base_glossary = json.loads(OLD_GLOSSARY_FILE.read_text())

    glossary = {}

    # 1. Apply overrides
    for term, data in OVERRIDES.items():
        glossary[term] = data

    # 2. Add exact matches from schema
    for table in schema_data["tables"]:
        table_name = table["name"]
        for col in table["columns"]:
            col_name = col["name"]
            if col_name in ["id", "created_at", "updated_at", "deleted_at"]:
                continue

            # Look for synonyms in base glossary
            syns = base_glossary.get(col_name, [])

            # Simple heuristic names
            term_name = f"{table_name}_{col_name}"
            if term_name not in glossary and col_name not in OVERRIDES:
                glossary[term_name] = {
                    "maps_to": f"{table_name}.{col_name}",
                    "note": "",
                    "synonyms": syns,
                }

    print(f"Writing column glossary with {len(glossary)} terms to {OUT_FILE}")
    OUT_FILE.write_text(json.dumps(glossary, indent=2))


if __name__ == "__main__":
    build_glossary()
