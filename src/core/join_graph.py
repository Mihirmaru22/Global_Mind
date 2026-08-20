"""
Join Graph Builder for validating SQL join paths against schema foreign keys.
"""
import logging
from typing import Dict, List, Set, Tuple, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ForeignKey:
    table: str
    column: str
    references_table: str
    references_column: str


@dataclass
class JoinPath:
    from_table: str
    to_table: str
    on_condition: str
    is_valid: bool = True


class JoinGraphBuilder:
    """Builds and validates join paths from schema atlas and canonical relationship registry."""
    
    def __init__(self, schema_atlas: Dict[str, Any], relationships: Optional[List[Dict[str, Any]]] = None):
        self.schema_atlas = schema_atlas or {}
        self.relationships = relationships
        self.tables: Set[str] = set()
        self.foreign_keys: List[ForeignKey] = []
        self.valid_joins: Set[Tuple[str, str]] = set()
        self._build_graph()
    
    def _build_graph(self):
        """Extract tables and foreign keys from schema atlas and canonical relationships registry."""
        # 1. From schema atlas
        for table_name, table_info in self.schema_atlas.get("tables", {}).items():
            self.tables.add(table_name.lower())
            for fk in table_info.get("foreign_keys", []):
                if isinstance(fk, dict):
                    ref_table = fk.get("references_table", "")
                    if ref_table:
                        self.foreign_keys.append(ForeignKey(
                            table=table_name.lower(),
                            column=fk.get("column", ""),
                            references_table=ref_table.lower(),
                            references_column=fk.get("references_column", "")
                        ))
                        self.valid_joins.add((table_name.lower(), ref_table.lower()))
                        self.valid_joins.add((ref_table.lower(), table_name.lower()))
        
        # 2. From canonical sql_relationships.json
        rels = self.relationships
        if rels is None:
            try:
                from src.stages.s12b_sql_retrieval import _get_raw_relationships
                rels = _get_raw_relationships()
            except Exception:
                rels = []
        
        for r in (rels or []):
            frm = (r.get("from_table") or "").lower()
            to = (r.get("to_table") or "").lower()
            fcol = r.get("from_column", "")
            tcol = r.get("to_column", "")
            if frm and to:
                self.tables.add(frm)
                self.tables.add(to)
                self.foreign_keys.append(ForeignKey(
                    table=frm,
                    column=fcol,
                    references_table=to,
                    references_column=tcol
                ))
                self.valid_joins.add((frm, to))
                self.valid_joins.add((to, frm))
        
        logger.info(f"Built join graph with {len(self.tables)} tables and {len(self.foreign_keys)} foreign keys")
    
    def get_valid_join_path(self, table1: str, table2: str) -> Optional[JoinPath]:
        """Check if a valid join path exists between two tables."""
        if (table1, table2) in self.valid_joins or (table2, table1) in self.valid_joins:
            # Find the FK that connects them
            for fk in self.foreign_keys:
                if (fk.table == table1 and fk.references_table == table2) or \
                   (fk.table == table2 and fk.references_table == table1):
                    return JoinPath(
                        from_table=fk.table,
                        to_table=fk.references_table,
                        on_condition=f"{fk.table}.{fk.column} = {fk.references_table}.{fk.references_column}"
                    )
        return None
    
    def validate_join_sequence(self, tables_in_query: List[str]) -> Tuple[bool, List[str]]:
        """Validate that a sequence of tables can be joined together."""
        if len(tables_in_query) <= 1:
            return True, []
        
        errors = []
        for i in range(len(tables_in_query) - 1):
            table1, table2 = tables_in_query[i], tables_in_query[i + 1]
            if (table1, table2) not in self.valid_joins and (table2, table1) not in self.valid_joins:
                errors.append(f"No valid join path between {table1} and {table2}")
        
        return len(errors) == 0, errors
    
    def extract_tables_from_sql(self, sql: str) -> List[str]:
        """Robust AST extraction of table names from SQL using sqlglot."""
        try:
            import sqlglot
            from sqlglot import exp
            ast = sqlglot.parse_one(sql)
            return sorted({t.name.lower() for t in ast.find_all(exp.Table) if t.name})
        except Exception:
            import re
            tables = []
            for pattern in [r'FROM\s+([a-zA-Z0-9_]+)', r'JOIN\s+([a-zA-Z0-9_]+)']:
                tables.extend(re.findall(pattern, sql, re.IGNORECASE))
            return sorted(set(t.lower() for t in tables))
    
    def validate_sql_joins(self, sql: str) -> Tuple[bool, List[str]]:
        """Validate all joins in a SQL query."""
        tables = self.extract_tables_from_sql(sql)
        return self.validate_join_sequence(tables)
