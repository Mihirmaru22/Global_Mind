"""Migration script to tag existing documents and chunks in Qdrant with user_id="system".

This ensures that pre-existing documents (e.g. SEC 10-Ks, company policies, benchmark fixtures)
remain accessible and queryable by all users under the new multi-tenant isolation model,
while newly ingested documents are isolated to their specific uploaders.

Usage:
    python scripts/migrate_existing_docs_to_system_user.py
    python scripts/migrate_existing_docs_to_system_user.py --collection globle_mind --dry-run
    python scripts/migrate_existing_docs_to_system_user.py --include-metadata-store
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import PointIdsList

from src.core.config import DATA_DIR, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def migrate_qdrant_collection(
    client: QdrantClient,
    collection_name: str,
    target_user: str = "system",
    batch_size: int = 250,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, int]:
    """Scroll through a Qdrant collection and tag points missing user_id with target_user."""
    logger.info("Checking Qdrant collection: '%s'...", collection_name)

    try:
        col_info = client.get_collection(collection_name)
        total_points = getattr(col_info, "points_count", 0) or 0
        logger.info("Found collection '%s' with ~%d points", collection_name, total_points)
    except Exception as e:
        logger.warning("Could not access collection '%s': %s", collection_name, e)
        return {"scanned": 0, "updated": 0, "already_tagged": 0}

    scanned = 0
    updated = 0
    already_tagged = 0
    next_offset = None

    while True:
        records, next_offset = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            break

        to_tag_ids = []
        for record in records:
            scanned += 1
            payload = record.payload or {}
            existing_user = payload.get("user_id")

            if existing_user is not None and not force:
                already_tagged += 1
            else:
                to_tag_ids.append(record.id)

        if to_tag_ids:
            if not dry_run:
                client.set_payload(
                    collection_name=collection_name,
                    payload={"user_id": target_user},
                    points=PointIdsList(points=to_tag_ids),
                )
            updated += len(to_tag_ids)

        if next_offset is None:
            break

    prefix = "[DRY RUN] " if dry_run else ""
    logger.info(
        "%sCollection '%s' complete: Scanned %d, Tagged %d with user_id='%s', Already Tagged %d",
        prefix,
        collection_name,
        scanned,
        updated,
        target_user,
        already_tagged,
    )
    return {"scanned": scanned, "updated": updated, "already_tagged": already_tagged}


def migrate_local_registry(
    registry_path: Path,
    target_user: str = "system",
    dry_run: bool = False,
) -> int:
    """Ensure all entries in the local JSON registry file have user_id set."""
    if not registry_path.exists():
        return 0

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Failed to read local registry %s: %s", registry_path, e)
        return 0

    updated_count = 0
    for doc_id, entry in data.items():
        if isinstance(entry, dict) and not entry.get("user_id"):
            entry["user_id"] = target_user
            updated_count += 1

    if updated_count > 0 and not dry_run:
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("Updated %d entries in local registry %s", updated_count, registry_path.name)
    elif updated_count > 0:
        logger.info("[DRY RUN] Would update %d entries in local registry %s", updated_count, registry_path.name)

    return updated_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate existing Qdrant points to system user.")
    parser.add_argument(
        "--collection",
        default="globle_mind",
        help="Target vector collection name (default: globle_mind)",
    )
    parser.add_argument(
        "--user-id",
        default="system",
        help="The user_id to tag legacy documents with (default: system)",
    )
    parser.add_argument(
        "--include-metadata-store",
        action="store_true",
        help="Also migrate the globle_mind_documents metadata collection",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing user_id values even if already set",
    )
    args = parser.parse_args()

    if not settings.qdrant_url:
        logger.warning("QDRANT_URL is not configured. Checking local registry only.")
        client = None
    else:
        logger.info("Connecting to Qdrant at %s...", settings.qdrant_url)
        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=30.0,
        )

    # 1. Migrate primary vector collection
    if client is not None:
        migrate_qdrant_collection(
            client=client,
            collection_name=args.collection,
            target_user=args.user_id,
            dry_run=args.dry_run,
            force=args.force,
        )

        # 2. Optionally migrate metadata documents collection
        if args.include_metadata_store:
            migrate_qdrant_collection(
                client=client,
                collection_name="globle_mind_documents",
                target_user=args.user_id,
                dry_run=args.dry_run,
                force=args.force,
            )

    # 3. Migrate local registry file if it exists
    local_registry_file = DATA_DIR / "ingested_files.json"
    migrate_local_registry(local_registry_file, target_user=args.user_id, dry_run=args.dry_run)

    logger.info("✅ Migration finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
