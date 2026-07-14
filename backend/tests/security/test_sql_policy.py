import pytest

from app.services.sql_policy import SqlPolicy, SqlPolicyViolation


def policy() -> SqlPolicy:
    return SqlPolicy(allowed_tables=("sales_channel_monthly",), max_rows=3)


def test_policy_accepts_select_and_applies_server_owned_limit() -> None:
    normalized = policy().validate(
        "SELECT month_start, channel, sales_amount FROM sales_channel_monthly"
    )

    assert normalized.sql.endswith("LIMIT 3")
    assert normalized.limit == 3


def test_policy_accepts_cte_select() -> None:
    normalized = policy().validate(
        "WITH monthly AS (SELECT channel, sales_amount FROM sales_channel_monthly) "
        "SELECT channel, SUM(sales_amount) AS total_sales FROM monthly GROUP BY channel"
    )

    assert normalized.sql.startswith("WITH")
    assert normalized.sql.endswith("LIMIT 3")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales_channel_monthly; DELETE FROM sales_channel_monthly",
        "INSERT INTO sales_channel_monthly (channel) VALUES ('online')",
        "UPDATE sales_channel_monthly SET channel = 'online'",
        "DELETE FROM sales_channel_monthly",
        "DROP TABLE sales_channel_monthly",
        "SELECT * INTO OUTFILE '/tmp/leak.csv' FROM sales_channel_monthly",
        "SELECT * FROM sales_channel_monthly FOR UPDATE",
    ],
)
def test_policy_rejects_non_readonly_or_multiple_statements(sql: str) -> None:
    with pytest.raises(SqlPolicyViolation):
        policy().validate(sql)


def test_policy_rejects_tables_outside_the_allowlist() -> None:
    with pytest.raises(SqlPolicyViolation):
        policy().validate("SELECT * FROM information_schema.tables")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'DROP TABLE sales_channel_monthly' AS message FROM sales_channel_monthly",
        "/* DELETE FROM sales_channel_monthly */ SELECT * FROM sales_channel_monthly",
    ],
)
def test_policy_does_not_reject_keywords_in_literals_or_comments(sql: str) -> None:
    assert policy().validate(sql).sql.endswith("LIMIT 3")


def test_policy_clamps_model_limit_instead_of_allowing_a_larger_result_set() -> None:
    normalized = policy().validate("SELECT * FROM sales_channel_monthly LIMIT 100")

    assert normalized.sql.endswith("LIMIT 3")
    assert normalized.limit == 3
