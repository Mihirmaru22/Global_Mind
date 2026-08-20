"""
Schema Drift Detection Engine
Monitors database schema changes and auto-heals the schema atlas.
"""
import json
import os
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SCHEMA_ATLAS_PATH = "config/schema_atlas.json"
DRIFT_LOG_PATH = "data/schema_drift_log.jsonl"


@dataclass
class SchemaDrift:
    drift_id: str
    drift_type: str  # new_table, missing_column, type_mismatch, new_column, deleted_column
    table_name: str
    column_name: Optional[str]
    expected_value: Any
    actual_value: Any
    severity: str  # critical, warning, info
    detected_at: str
    auto_healed: bool = False


class SchemaMonitor:
    """Monitors database schema for drift and triggers auto-healing."""
    
    def __init__(self, db_client: Any, atlas_path: str = SCHEMA_ATLAS_PATH):
        self.db_client = db_client
        self.atlas_path = atlas_path
        self.cached_atlas: Dict[str, Any] = {}
        self._load_cached_atlas()
    
    def _load_cached_atlas(self):
        """Load the cached schema atlas."""
        if not os.path.exists(self.atlas_path):
            logger.warning(f"Schema atlas not found at {self.atlas_path}")
            return
        
        try:
            with open(self.atlas_path, 'r', encoding='utf-8') as f:
                self.cached_atlas = json.load(f)
            logger.info(f"Loaded schema atlas with {len(self.cached_atlas.get('tables', {}))} tables")
        except Exception as e:
            logger.error(f"Failed to load schema atlas: {e}")
    
    async def check_for_drift(self) -> List[SchemaDrift]:
        """Compare live database schema against cached atlas."""
        drifts = []
        
        try:
            # Get live schema from database
            live_schema = await self._fetch_live_schema()
            
            # Compare tables
            cached_tables = set(self.cached_atlas.get("tables", {}).keys())
            live_tables = set(live_schema.get("tables", {}).keys())
            
            # Check for new tables
            new_tables = live_tables - cached_tables
            for table in new_tables:
                drift = SchemaDrift(
                    drift_id=f"new_table_{table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    drift_type="new_table",
                    table_name=table,
                    column_name=None,
                    expected_value=None,
                    actual_value=live_schema["tables"][table],
                    severity="warning",
                    detected_at=datetime.now().isoformat()
                )
                drifts.append(drift)
                self._log_drift(drift)
            
            # Check for deleted tables
            deleted_tables = cached_tables - live_tables
            for table in deleted_tables:
                drift = SchemaDrift(
                    drift_id=f"deleted_table_{table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    drift_type="deleted_table",
                    table_name=table,
                    column_name=None,
                    expected_value=self.cached_atlas["tables"][table],
                    actual_value=None,
                    severity="critical",
                    detected_at=datetime.now().isoformat()
                )
                drifts.append(drift)
                self._log_drift(drift)
            
            # Check columns in existing tables
            for table in cached_tables & live_tables:
                column_drifts = self._compare_columns(
                    table,
                    self.cached_atlas["tables"][table].get("columns", {}),
                    live_schema["tables"][table].get("columns", {})
                )
                drifts.extend(column_drifts)
            
            # Auto-heal if appropriate
            healable_drifts = [d for d in drifts if self._is_healable(d)]
            if healable_drifts:
                await self._auto_heal(healable_drifts, live_schema)
            
            return drifts
            
        except Exception as e:
            logger.error(f"Failed to check for schema drift: {e}")
            return []
    
    def _compare_columns(self, table: str, 
                        cached_cols: Dict[str, Any], 
                        live_cols: Dict[str, Any]) -> List[SchemaDrift]:
        """Compare columns between cached and live schema."""
        drifts = []
        now = datetime.now().isoformat()
        
        cached_col_names = set(cached_cols.keys())
        live_col_names = set(live_cols.keys())
        
        # New columns
        for col in live_col_names - cached_col_names:
            drift = SchemaDrift(
                drift_id=f"new_col_{table}_{col}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                drift_type="new_column",
                table_name=table,
                column_name=col,
                expected_value=None,
                actual_value=live_cols[col],
                severity="info",
                detected_at=now
            )
            drifts.append(drift)
            self._log_drift(drift)
        
        # Deleted columns
        for col in cached_col_names - live_col_names:
            drift = SchemaDrift(
                drift_id=f"deleted_col_{table}_{col}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                drift_type="deleted_column",
                table_name=table,
                column_name=col,
                expected_value=cached_cols[col],
                actual_value=None,
                severity="critical",
                detected_at=now
            )
            drifts.append(drift)
            self._log_drift(drift)
        
        # Type mismatches
        for col in cached_col_names & live_col_names:
            cached_type = cached_cols[col].get("type", "").upper()
            live_type = live_cols[col].get("type", "").upper()
            
            if cached_type != live_type:
                drift = SchemaDrift(
                    drift_id=f"type_mismatch_{table}_{col}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    drift_type="type_mismatch",
                    table_name=table,
                    column_name=col,
                    expected_value=cached_type,
                    actual_value=live_type,
                    severity="warning",
                    detected_at=now
                )
                drifts.append(drift)
                self._log_drift(drift)
        
        return drifts
    
    def _is_healable(self, drift: SchemaDrift) -> bool:
        """Determine if a drift can be auto-healed."""
        healable_types = ["new_column", "new_table"]
        return drift.drift_type in healable_types and drift.severity != "critical"
    
    async def _auto_heal(self, drifts: List[SchemaDrift], live_schema: Dict[str, Any]):
        """Auto-heal healable drifts by updating the cached atlas."""
        logger.info(f"Auto-healing {len(drifts)} schema drifts")
        
        for drift in drifts:
            if drift.drift_type == "new_column":
                # Add new column to cached atlas
                if drift.table_name in self.cached_atlas.get("tables", {}):
                    self.cached_atlas["tables"][drift.table_name]["columns"][drift.column_name] = {
                        "type": drift.actual_value.get("type"),
                        "nullable": drift.actual_value.get("nullable", True)
                    }
                    drift.auto_healed = True
                    logger.info(f"Auto-healed: Added column {drift.column_name} to {drift.table_name}")
            
            elif drift.drift_type == "new_table":
                # Add new table to cached atlas
                self.cached_atlas["tables"][drift.table_name] = live_schema["tables"][drift.table_name]
                drift.auto_healed = True
                logger.info(f"Auto-healed: Added table {drift.table_name}")
        
        # Save updated atlas
        self._save_cached_atlas()
    
    def _save_cached_atlas(self):
        """Save the updated schema atlas."""
        try:
            os.makedirs(os.path.dirname(self.atlas_path), exist_ok=True)
            with open(self.atlas_path, 'w', encoding='utf-8') as f:
                json.dump(self.cached_atlas, f, indent=2)
            logger.info("Saved updated schema atlas")
        except Exception as e:
            logger.error(f"Failed to save schema atlas: {e}")
    
    def _log_drift(self, drift: SchemaDrift):
        """Log drift to JSONL file."""
        try:
            os.makedirs(os.path.dirname(DRIFT_LOG_PATH), exist_ok=True)
            with open(DRIFT_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    "drift_id": drift.drift_id,
                    "drift_type": drift.drift_type,
                    "table_name": drift.table_name,
                    "column_name": drift.column_name,
                    "severity": drift.severity,
                    "detected_at": drift.detected_at,
                    "auto_healed": drift.auto_healed
                }) + '\n')
        except Exception as e:
            logger.error(f"Failed to log drift: {e}")
    
    async def _fetch_live_schema(self) -> Dict[str, Any]:
        """Fetch current schema from database."""
        # This would use the db_client to query INFORMATION_SCHEMA
        # Simplified for demonstration
        return await self.db_client.get_full_schema()
    
    async def run_periodic_check(self):
        """Run periodic schema drift check (called by scheduler)."""
        logger.info("Running periodic schema drift check")
        drifts = await self.check_for_drift()
        
        critical_drifts = [d for d in drifts if d.severity == "critical"]
        if critical_drifts:
            logger.warning(f"Detected {len(critical_drifts)} critical schema drifts - manual review required")
            # Could trigger alert here
        
        return len(drifts)
