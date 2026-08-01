from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from backend.resource_library.database_tools import QueryResult, ReadonlyDatabaseTools


class ReportQueryNotFound(ValueError):
    pass


class ReportQueryFilterError(ValueError):
    pass


CHANNEL_SALES_QUERY_REF = "finereport-operation-management-channel-sales"
REGION_CHANNEL_SALES_QUERY_REF = "finereport-operation-management-region-channel-sales"
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_FILTER_KEYS = {"month", "brand", "region"}


@dataclass(frozen=True)
class ReportQueryResponse:
    queryRef: str
    filters: dict[str, str]
    columns: list[str]
    rows: list[dict[str, Any]]
    rowCount: int
    elapsedMs: int
    truncated: bool


class ReportQueryAuditStore(Protocol):
    def record_query(
        self,
        *,
        query_ref: str,
        filters: dict[str, str],
        response: ReportQueryResponse,
        context: dict[str, Any],
    ) -> None: ...


class ReportQueryService:
    """Server-owned report query registry; it deliberately accepts no browser SQL."""

    def __init__(self, db_tools: ReadonlyDatabaseTools, audit_store: ReportQueryAuditStore | None = None) -> None:
        self.db_tools = db_tools
        self.audit_store = audit_store

    def run(
        self,
        query_ref: str,
        filters: dict[str, Any],
        *,
        audit_context: dict[str, Any] | None = None,
    ) -> ReportQueryResponse:
        if query_ref not in {CHANNEL_SALES_QUERY_REF, REGION_CHANNEL_SALES_QUERY_REF}:
            raise ReportQueryNotFound("report_query_not_found")
        normalized_filters = _normalize_channel_sales_filters(filters)
        sql, parameters = _channel_sales_sql(
            normalized_filters,
            group_by_region=query_ref == REGION_CHANNEL_SALES_QUERY_REF,
        )
        result = self.db_tools.run_readonly_template(
            sql,
            parameters,
            reason=f"interactive_report_query:{query_ref}",
            max_rows=100,
        )
        rows = _with_sales_share(result)
        response = ReportQueryResponse(
            queryRef=query_ref,
            filters=normalized_filters,
            columns=[*result.columns, "salesShare"],
            rows=rows,
            rowCount=len(rows),
            elapsedMs=result.elapsed_ms,
            truncated=result.truncated,
        )
        if self.audit_store:
            self.audit_store.record_query(
                query_ref=query_ref,
                filters=normalized_filters,
                response=response,
                context=dict(audit_context or {}),
            )
        return response


def response_to_dict(response: ReportQueryResponse) -> dict[str, Any]:
    return asdict(response)


def build_report_query_prompt_context() -> str:
    """Describe only the report query contracts currently safe for Codex to reference."""

    return "\n".join(
        [
            "当前已登记的交互式报告查询（只能引用以下 queryRef，不能创造新的 SQL 或 queryRef）：",
            f"- {CHANNEL_SALES_QUERY_REF}",
            "  - 来源：FineReport 财务经营管报日报 / dm.dm_fina_operation_mgmt_rpt。",
            "  - 运行时筛选：month（必填 YYYY-MM）、brand、region；brand/region 可为 all。",
            "  - 返回字段：channel、salesAmount、netRevenue、refundAmount、salesShare。",
            "  - 口径：salesAmount 聚合科目“销售额”；netRevenue 聚合“收入净额”；refundAmount 聚合“退款金额”；salesShare 由服务端按当前筛选范围计算。",
            f"- {REGION_CHANNEL_SALES_QUERY_REF}",
            "  - 来源和筛选同上；按线下区域（vregion）和渠道类型（vchannel_type）共同汇总。",
            "  - 返回字段：region、channel、salesAmount、netRevenue、refundAmount、salesShare。",
        ]
    )


def is_registered_report_query_ref(query_ref: str) -> bool:
    return query_ref in {CHANNEL_SALES_QUERY_REF, REGION_CHANNEL_SALES_QUERY_REF}


def _normalize_channel_sales_filters(filters: dict[str, Any]) -> dict[str, str]:
    if not isinstance(filters, dict):
        raise ReportQueryFilterError("report_query_filters_invalid")
    unexpected = sorted(set(filters) - _FILTER_KEYS)
    if unexpected:
        raise ReportQueryFilterError(f"report_query_filter_not_allowed: {', '.join(unexpected)}")
    month = str(filters.get("month") or "").strip()
    if not _MONTH_RE.fullmatch(month):
        raise ReportQueryFilterError("report_query_month_required")
    normalized = {"month": month}
    for key in ("brand", "region"):
        value = str(filters.get(key) or "").strip()
        if value and value != "all":
            if len(value) > 100:
                raise ReportQueryFilterError(f"report_query_{key}_invalid")
            normalized[key] = value
    return normalized


def _channel_sales_sql(filters: dict[str, str], *, group_by_region: bool = False) -> tuple[str, dict[str, str]]:
    conditions = [
        "vmonth_code = :month",
        "vsubject IN ('销售额', '收入净额', '退款金额')",
    ]
    parameters = {"month": filters["month"]}
    for key, column in (("brand", "vbrand"), ("region", "vregion")):
        if key in filters:
            conditions.append(f"{column} = :{key}")
            parameters[key] = filters[key]
    dimensions = ["COALESCE(NULLIF(vchannel_type, ''), '未分类') AS channel"]
    group_by = ["COALESCE(NULLIF(vchannel_type, ''), '未分类')"]
    if group_by_region:
        dimensions.insert(0, "COALESCE(NULLIF(vregion, ''), '未分类') AS region")
        group_by.insert(0, "COALESCE(NULLIF(vregion, ''), '未分类')")
    sql = "\n".join(
        [
            "SELECT",
            *[f"  {dimension}," for dimension in dimensions],
            "  SUM(CASE WHEN vsubject = '销售额' THEN vvalues ELSE 0 END) AS salesAmount,",
            "  SUM(CASE WHEN vsubject = '收入净额' THEN vvalues ELSE 0 END) AS netRevenue,",
            "  SUM(CASE WHEN vsubject = '退款金额' THEN vvalues ELSE 0 END) AS refundAmount",
            "FROM dm.dm_fina_operation_mgmt_rpt",
            f"WHERE {' AND '.join(conditions)}",
            f"GROUP BY {', '.join(group_by)}",
            "ORDER BY salesAmount DESC, channel ASC",
        ]
    )
    return sql, parameters


def _with_sales_share(result: QueryResult) -> list[dict[str, Any]]:
    total = sum(float(row.get("salesAmount") or 0) for row in result.rows)
    rows: list[dict[str, Any]] = []
    for row in result.rows:
        normalized = {key: _json_value(value) for key, value in row.items()}
        sales_amount = float(normalized.get("salesAmount") or 0)
        normalized["salesShare"] = sales_amount / total if total else 0
        rows.append(normalized)
    return rows


def _json_value(value: Any) -> Any:
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)
