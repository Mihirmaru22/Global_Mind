#!/usr/bin/env python3
"""
Generate LLM predictions in small, rate-limited chunks.

IMPORTANT: only the QUESTION is sent to the generator.
Wired to the GlobalMind Text-to-SQL retriever (src.stages.s12b_sql_retrieval).
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    import dotenv
    dotenv.load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from src.core.provider_client import ProviderRouter
from src.stages.s12b_sql_retrieval import SQLRetriever

SCRIPT_DIR = Path(__file__).resolve().parent
DATASET = SCRIPT_DIR / "phase1_golden_dataset.jsonl"
OUT = SCRIPT_DIR / "predictions.jsonl"


async def main_async(args):
    dataset_path = Path(args.dataset)
    out_path = Path(args.out)

    done = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        if record.get("generated_sql") is not None:
                            done.add(record["id"])
                    except Exception:
                        pass

    cases = [json.loads(l) for l in dataset_path.open(encoding="utf-8") if l.strip()]
    if args.suite:
        cases = [c for c in cases if c["suite"] == args.suite]
    cases = [c for c in cases if c["id"] not in done and c.get("expected_outcome") == "execute"][:args.limit]

    print(f"Generating predictions for {len(cases)} cases (suite: {args.suite or 'all'}, limit: {args.limit})...")
    if not cases:
        print("No remaining cases to process.")
        return

    router = ProviderRouter()
    retriever = SQLRetriever(router)

    with out_path.open("a", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            cid = case["id"]
            q = case["question"]
            print(f"[{i}/{len(cases)}] Generating for {cid}: {q}")
            sql = None
            try:
                schema = await retriever._get_schema(q)
                sql = await retriever._generate_sql(q, schema)
                if not sql:
                    print(f"  -> WARNING: Empty SQL returned.")
                else:
                    print(f"  -> OK")
            except Exception as exc:  # noqa: BLE001
                sql = None
                print(f"  -> ERROR: {exc}")

            f.write(json.dumps({"id": cid, "generated_sql": sql}, ensure_ascii=False) + "\n")
            f.flush()
            if args.delay > 0 and i < len(cases):
                await asyncio.sleep(args.delay)

    print(f"\nCompleted. Predictions written to {out_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Generate SQL predictions for benchmark questions.")
    parser.add_argument("--limit", type=int, default=20, help="Max questions to predict")
    parser.add_argument("--suite", default=None, help="Filter by benchmark suite")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between LLM calls")
    parser.add_argument("--dataset", default=str(DATASET), help="Path to golden dataset jsonl")
    parser.add_argument("--out", default=str(OUT), help="Output predictions jsonl file")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()