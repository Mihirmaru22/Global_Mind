"""Tests for the Schema-Aware Column Registry."""

import pytest
from src.core.sql_column_registry import ColumnRegistry


@pytest.fixture
def sqlite_schema() -> str:
    return """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        name TEXT,
        email TEXT UNIQUE,
        created_at DATETIME
    );
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        total_amount REAL,
        status TEXT
    );
    """


@pytest.fixture
def mysql_schema() -> str:
    return """
TABLE users (
  id int(11),
  name varchar(255),
  email varchar(255),
  created_at datetime
)

TABLE orders (
  id int(11),
  user_id int(11),
  total_amount decimal(10,2),
  status varchar(50)
)
"""


def test_sqlite_parsing(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    assert "users" in registry._tables
    assert "orders" in registry._tables
    assert registry._tables["users"] == {"id", "name", "email", "created_at"}
    assert registry._tables["orders"] == {"id", "user_id", "total_amount", "status"}


def test_mysql_parsing(mysql_schema: str) -> None:
    registry = ColumnRegistry(mysql_schema, "mysql")
    assert "users" in registry._tables
    assert registry._tables["users"] == {"id", "name", "email", "created_at"}


def test_valid_sql_passes_validation(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "SELECT id, name FROM users WHERE email = 'test@example.com'"
    result = registry.validate_columns(sql)
    assert result.is_valid
    assert not result.errors


def test_valid_sql_with_aliases_passes(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "SELECT u.name, o.total_amount FROM users u JOIN orders o ON u.id = o.user_id"
    result = registry.validate_columns(sql)
    assert result.is_valid


def test_hallucinated_column_caught(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "SELECT id, astrological_sign FROM users"
    result = registry.validate_columns(sql)
    assert not result.is_valid
    assert len(result.errors) == 1
    assert "astrological_sign" in result.errors[0]
    assert "users" in result.errors[0]
    assert result.hallucinated_columns == ["astrological_sign"]


def test_hallucinated_qualified_column_caught(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "SELECT u.name, o.gpu_model FROM users u JOIN orders o ON u.id = o.user_id"
    result = registry.validate_columns(sql)
    assert not result.is_valid
    assert "gpu_model" in result.errors[0]
    assert "orders" in result.errors[0]
    assert result.hallucinated_columns == ["orders.gpu_model"]


def test_unqualified_column_resolved_via_from(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "SELECT total_amount FROM orders"
    result = registry.validate_columns(sql)
    assert result.is_valid


def test_cte_columns_validated(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = """
    WITH recent_orders AS (
        SELECT user_id, fake_column FROM orders
    )
    SELECT u.name FROM users u JOIN recent_orders r ON u.id = r.user_id
    """
    result = registry.validate_columns(sql)
    assert not result.is_valid
    assert "fake_column" in result.errors[0]
    assert result.hallucinated_columns == ["fake_column"]


def test_alias_from_question_flagged(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "SELECT status AS technology_used FROM orders"
    question = "What technology is used the most?"
    warnings = registry.validate_aliases(sql, question)
    assert len(warnings) == 1
    assert "technology_used" in warnings[0]


def test_alias_from_schema_not_flagged(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    # 'name' is a real column, even if it's in the question.
    sql = "SELECT name AS name FROM users"
    question = "What is the name of the user?"
    warnings = registry.validate_aliases(sql, question)
    assert len(warnings) == 0


def test_alias_aggregate_flagged(sqlite_schema: str) -> None:
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "SELECT SUM(total_amount) AS technology_used FROM orders"
    question = "What technology is used the most?"
    warnings = registry.validate_aliases(sql, question)
    assert len(warnings) == 1
    assert "technology_used" in warnings[0]
    assert "total_amount" in warnings[0]


def test_double_quoted_literals_in_sqlite_not_flagged(sqlite_schema: str) -> None:
    """In SQLite dialect, double-quoted non-column tokens (e.g. status = 'completed')
    compared against real columns must not be flagged as hallucinated columns."""
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = 'SELECT id, total_amount FROM orders WHERE status = "completed"'
    result = registry.validate_columns(sql)
    assert result.is_valid
    assert not result.errors


def test_hallucinated_double_quoted_column_flagged(sqlite_schema: str) -> None:
    """A genuinely hallucinated column wrapped in double quotes (projection, compared to literal,
    or in ORDER BY) must be caught and flagged as an error, NOT excused by the string literal fallback."""
    registry = ColumnRegistry(sqlite_schema, "sqlite")

    # 1. Hallucinated column in SELECT projection
    res1 = registry.validate_columns('SELECT "astrological_sign" FROM users')
    assert not res1.is_valid
    assert "astrological_sign" in res1.errors[0]
    assert "astrological_sign" in res1.hallucinated_columns

    # 2. Hallucinated column compared to a number
    res2 = registry.validate_columns('SELECT id FROM users WHERE "totally_fake_column" = 1')
    assert not res2.is_valid
    assert "totally_fake_column" in res2.errors[0]
    assert "totally_fake_column" in res2.hallucinated_columns

    # 3. Hallucinated column in ORDER BY
    res3 = registry.validate_columns('SELECT id FROM users ORDER BY "fake_sort_col"')
    assert not res3.is_valid
    assert "fake_sort_col" in res3.errors[0]
    assert "fake_sort_col" in res3.hallucinated_columns


def test_cte_shadowing_caught_in_column_registry(sqlite_schema: str) -> None:
    """CTE shadowing physical table in ColumnRegistry is blocked."""
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "WITH users AS (SELECT 1 AS dummy) SELECT * FROM users"
    result = registry.validate_columns(sql)
    assert not result.is_valid
    assert any("CTE table shadowing" in e for e in result.errors)


def test_cte_hallucinated_column_caught_in_column_registry(sqlite_schema: str) -> None:
    """CTE defining completely unrecognized columns is caught and blocked."""
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = "WITH custom_cte AS (SELECT 1 AS shadow_token, 9999.99 AS fake_credit_limit) SELECT c.shadow_token FROM custom_cte c"
    result = registry.validate_columns(sql)
    assert not result.is_valid
    assert any("shadow_token" in e for e in result.errors)
    assert "custom_cte.shadow_token" in result.hallucinated_columns


def test_cte_valid_metric_aliases_pass_in_column_registry(sqlite_schema: str) -> None:
    """CTE projecting valid aggregates and business metrics passes."""
    registry = ColumnRegistry(sqlite_schema, "sqlite")
    sql = """
    WITH order_summary AS (
        SELECT user_id, SUM(total_amount) AS total_spent, COUNT(id) AS order_count
        FROM orders
        GROUP BY user_id
    )
    SELECT u.name, os.total_spent, os.order_count
    FROM users u
    JOIN order_summary os ON u.id = os.user_id
    """
    result = registry.validate_columns(sql)
    assert result.is_valid
    assert not result.errors

