"""
Semantic Correctness Validation Engine
Validates SQL queries and results for logical correctness before returning to users.
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    passed: bool
    severity: ValidationSeverity
    message: str
    context: Dict[str, Any]


class CardinalityValidator:
    """Detects cross joins and row count explosions."""
    
    def __init__(self, max_rows: int = 10000, cross_join_threshold: int = 1000):
        self.max_rows = max_rows
        self.cross_join_threshold = cross_join_threshold
    
    def validate(self, sql: str, estimated_rows: Optional[int] = None) -> ValidationResult:
        # Check for missing JOIN conditions (potential cross joins)
        if "CROSS JOIN" in sql.upper():
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.CRITICAL,
                message="Cross join detected without explicit intent",
                context={"sql_fragment": "CROSS JOIN"}
            )
        
        # Check for JOINs without ON clauses
        if "JOIN" in sql.upper() and "ON" not in sql.upper():
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.CRITICAL,
                message="JOIN without ON clause detected",
                context={"issue": "missing_on_clause"}
            )
        
        if estimated_rows and estimated_rows > self.max_rows:
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                message=f"Estimated row count ({estimated_rows}) exceeds threshold",
                context={"estimated_rows": estimated_rows, "threshold": self.max_rows}
            )
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            message="Cardinality checks passed",
            context={}
        )


class JoinPathValidator:
    """Validates that joins follow valid foreign key relationships."""
    
    def __init__(self, schema_atlas: Dict[str, Any], relationships: Optional[List[Dict[str, Any]]] = None):
        self.schema_atlas = schema_atlas or {}
        self.relationships = relationships
        self.valid_paths = self._build_valid_paths()
    
    def _build_valid_paths(self) -> set:
        paths = set()
        # 1. From schema atlas
        for table_name, table_info in self.schema_atlas.get("tables", {}).items():
            for fk in table_info.get("foreign_keys", []):
                ref_table = fk.get("references_table")
                if ref_table:
                    paths.add((table_name.lower(), ref_table.lower()))
                    paths.add((ref_table.lower(), table_name.lower()))
        # 2. From canonical relationships registry (config/sql_relationships.json)
        rels = self.relationships
        if rels is None:
            try:
                from src.stages.s12b_sql_retrieval import _get_raw_relationships
                rels = _get_raw_relationships()
            except Exception:
                rels = []
        for r in (rels or []):
            f_tbl = (r.get("from_table") or "").lower()
            t_tbl = (r.get("to_table") or "").lower()
            if f_tbl and t_tbl:
                paths.add((f_tbl, t_tbl))
                paths.add((t_tbl, f_tbl))
        return paths
    
    def validate(self, sql: str, tables_involved: List[str]) -> ValidationResult:
        if len(tables_involved) <= 1 or not self.valid_paths:
            return ValidationResult(
                passed=True,
                severity=ValidationSeverity.INFO,
                message="Single table or unmapped schema - join validation skipped",
                context={}
            )
        
        tables_lower = [t.lower() for t in tables_involved]
        
        # Verify that every table in the query is connected to at least one other table in the query
        isolated_tables = []
        for t1 in tables_lower:
            has_connection = any(
                (t1, t2) in self.valid_paths or (t2, t1) in self.valid_paths
                for t2 in tables_lower if t1 != t2
            )
            if not has_connection:
                isolated_tables.append(t1)
        
        if isolated_tables:
            logger.warning(f"Tables without valid join path to any query table: {isolated_tables}")
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                message=f"No defined relationship between {', '.join(isolated_tables)} and other tables in query",
                context={"isolated_tables": isolated_tables, "tables": tables_involved}
            )
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            message="All join paths validated against schema graph",
            context={"tables": tables_involved}
        )


class TemporalValidator:
    """Validates date logic and soft-delete filters."""
    
    def validate(self, sql: str, has_date_filter: bool = False) -> ValidationResult:
        sql_upper = sql.upper()
        
        # Check for malformed soft-delete syntax (e.g. deleted_at = NULL instead of IS NULL)
        if "DELETED_AT" in sql_upper and "DELETED_AT = NULL" in sql_upper:
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                message="Malformed soft-delete syntax: use 'deleted_at IS NULL', not '= NULL'",
                context={"recommendation": "Use WHERE ...deleted_at IS NULL"}
            )
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            message="Temporal validation passed",
            context={"has_date_filter": has_date_filter}
        )


class AggregationValidator:
    """Validates GROUP BY and aggregation logic."""
    
    def validate(self, sql: str, has_aggregation: bool = False) -> ValidationResult:
        sql_upper = sql.upper()
        agg_funcs = ["SUM(", "AVG(", "COUNT(", "MAX(", "MIN("]
        has_agg = any(func in sql_upper for func in agg_funcs)
        
        if has_agg:
            if "GROUP BY" not in sql_upper and sql_upper.count(",") > 0 and "SELECT" in sql_upper:
                logger.debug("Aggregation without GROUP BY detected")
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            message="Aggregation validation passed",
            context={"has_aggregation": has_agg}
        )


class DataTypeValidator:
    """Catches implicit type conversion risks on VARCHAR columns."""
    
    def validate(self, sql: str, schema_context: Dict[str, Any]) -> ValidationResult:
        import re
        varchar_columns = []
        for table_info in schema_context.get("tables", {}).values():
            for col_name, col_info in table_info.get("columns", {}).items():
                if any(t in col_info.get("type", "").upper() for t in ["VARCHAR", "TEXT", "CHAR"]):
                    if any(m in col_name.lower() for m in ["qty", "quantity", "rate", "amount", "price", "weight", "total", "cost", "apq"]):
                        varchar_columns.append(col_name)
        
        # Warn if numeric operations detected on VARCHAR columns without CAST
        sql_upper = sql.upper()
        for col in set(varchar_columns):
            pattern = rf"\b(?:SUM|AVG)\s*\(\s*(?:[a-zA-Z0-9_]+\.)?{re.escape(col)}\b"
            if re.search(pattern, sql, re.IGNORECASE):
                if "CAST(" not in sql_upper:
                    return ValidationResult(
                        passed=False,
                        severity=ValidationSeverity.WARNING,
                        message=f"Aggregation on VARCHAR column '{col}' without CAST",
                        context={"column": col, "recommendation": f"Apply CAST({col} AS DECIMAL(10,2)) before aggregation"}
                    )
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            message="Data type validation passed",
            context={}
        )


class ResultSanityValidator:
    """Statistical outlier detection on returned results."""
    
    def validate(self, results: List[Dict[str, Any]], expected_range: Optional[Tuple[float, float]] = None) -> ValidationResult:
        if not results:
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                message="Empty result set returned",
                context={"issue": "empty_results"}
            )
        
        # Check for NULL-only results in aggregations
        if len(results) == 1:
            first_row = results[0]
            null_count = sum(1 for v in first_row.values() if v is None)
            if null_count == len(first_row):
                return ValidationResult(
                    passed=False,
                    severity=ValidationSeverity.WARNING,
                    message="All values in result are NULL",
                    context={"issue": "all_null_results"}
                )
        
        # Check for extreme outliers
        numeric_values = []
        for row in results[:100]:  # Sample first 100 rows
            for value in row.values():
                if isinstance(value, (int, float)) and value is not None:
                    numeric_values.append(value)
        
        if numeric_values:
            avg = sum(numeric_values) / len(numeric_values)
            if any(abs(v - avg) > 10 * avg for v in numeric_values if avg != 0):
                logger.warning("Potential outlier detected in results")
                return ValidationResult(
                    passed=True,
                    severity=ValidationSeverity.INFO,
                    message="Results contain statistical outliers - verify correctness",
                    context={"average": avg, "outlier_detected": True}
                )
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            message="Result sanity checks passed",
            context={"row_count": len(results)}
        )


class ResultValidator:
    """Main validation engine orchestrating all validators."""
    
    def __init__(self, schema_atlas: Dict[str, Any], config: Optional[Dict[str, Any]] = None):
        self.schema_atlas = schema_atlas or {}
        self.config = config or {}
        self.cardinality_validator = CardinalityValidator(
            max_rows=self.config.get("max_rows", 10000)
        )
        self.join_path_validator = JoinPathValidator(self.schema_atlas)
        self.temporal_validator = TemporalValidator()
        self.aggregation_validator = AggregationValidator()
        self.data_type_validator = DataTypeValidator()
        self.result_sanity_validator = ResultSanityValidator()
    
    def validate_query(self, sql: str, tables_involved: List[str], 
                      has_date_filter: bool = False, has_aggregation: bool = False,
                      estimated_rows: Optional[int] = None) -> List[ValidationResult]:
        """Pre-execution validation of SQL query."""
        results = []
        
        results.append(self.cardinality_validator.validate(sql, estimated_rows))
        results.append(self.join_path_validator.validate(sql, tables_involved))
        results.append(self.temporal_validator.validate(sql, has_date_filter))
        results.append(self.aggregation_validator.validate(sql, has_aggregation))
        results.append(self.data_type_validator.validate(sql, self.schema_atlas))
        
        return results
    
    def validate_results(self, results: List[Dict[str, Any]], 
                        expected_range: Optional[Tuple[float, float]] = None) -> ValidationResult:
        """Post-execution validation of results."""
        return self.result_sanity_validator.validate(results, expected_range)
    
    def calculate_confidence_score(self, validation_results: List[ValidationResult]) -> float:
        """Calculate overall confidence score based on validation results."""
        if not validation_results:
            return 1.0
        
        critical_failures = sum(1 for r in validation_results if r.severity == ValidationSeverity.CRITICAL and not r.passed)
        warning_failures = sum(1 for r in validation_results if r.severity == ValidationSeverity.WARNING and not r.passed)
        
        # Deduct points for failures
        score = 1.0
        score -= critical_failures * 0.3
        score -= warning_failures * 0.1
        
        return max(0.0, min(1.0, score))
