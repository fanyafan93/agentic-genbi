from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.reports.query_service import (
    UnsafeReportQuery,
    query_parameter_names,
)


FILTER_TYPES = {"select", "multiSelect", "date", "dateRange"}
LEGACY_REPORT_FIELDS = {
    "artifactType",
    "renderer",
    "schemaVersion",
    "document",
    "chartSpecs",
    "gridSpecs",
    "datasets",
    "source",
    "sourceThreadId",
    "sourceTurnId",
}


class ReportValidationError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.message = message


def validate_report_config(report: Mapping[str, Any]) -> None:
    if not isinstance(report, Mapping):
        raise ReportValidationError("report", "report must be an object.")
    for key in LEGACY_REPORT_FIELDS:
        if key in report:
            raise ReportValidationError(
                key,
                f"{key} is not part of the Report contract.",
            )
    _require_text(report, "title")
    _require_text(report, "subtitle")
    for key in ("layout", "filters", "charts", "tables", "queries"):
        if not isinstance(report.get(key), dict):
            raise ReportValidationError(key, f"{key} must be an object.")

    filters = report["filters"]
    queries = report["queries"]
    charts = report["charts"]
    tables = report["tables"]
    layout = report["layout"]
    _validate_filters(filters)
    _validate_queries(queries, filters)
    _validate_charts(charts, queries)
    _validate_tables(tables, queries)
    _validate_layout(layout, filters, charts, tables)


def report_config_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    validate_report_config(report)
    return {
        "title": str(report["title"]).strip(),
        "subtitle": str(report["subtitle"]).strip(),
        "layout": dict(report["layout"]),
        "filters": dict(report["filters"]),
        "charts": dict(report["charts"]),
        "tables": dict(report["tables"]),
        "queries": dict(report["queries"]),
    }


def _validate_filters(filters: dict[str, Any]) -> None:
    for filter_id, value in filters.items():
        path = f"filters.{filter_id}"
        if not isinstance(value, dict):
            raise ReportValidationError(path, "filter must be an object.")
        filter_type = value.get("type")
        if filter_type not in FILTER_TYPES:
            raise ReportValidationError(
                f"{path}.type",
                f"filter type must be one of {sorted(FILTER_TYPES)}.",
            )
        _require_nested_text(value, "label", path)
        if filter_type in {"select", "multiSelect"}:
            options = value.get("options")
            if not isinstance(options, list):
                raise ReportValidationError(
                    f"{path}.options",
                    "select filter options must be an array.",
                )
            for index, option in enumerate(options):
                if not isinstance(option, dict):
                    raise ReportValidationError(
                        f"{path}.options.{index}",
                        "filter option must be an object.",
                    )
                _require_nested_text(
                    option,
                    "label",
                    f"{path}.options.{index}",
                )
                if "value" not in option:
                    raise ReportValidationError(
                        f"{path}.options.{index}.value",
                        "filter option value is required.",
                    )


def _validate_queries(
    queries: dict[str, Any],
    filters: dict[str, Any],
) -> None:
    for query_id, value in queries.items():
        path = f"queries.{query_id}"
        if not isinstance(value, dict):
            raise ReportValidationError(path, "query must be an object.")
        _require_nested_text(value, "dataSource", path)
        _require_nested_text(value, "sql", path)
        try:
            placeholder_names = query_parameter_names(str(value["sql"]))
        except UnsafeReportQuery as exc:
            raise ReportValidationError(
                f"{path}.sql",
                str(exc),
            ) from exc
        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ReportValidationError(
                f"{path}.parameters",
                "query parameters must be an object.",
            )
        parameter_names = {str(name) for name in parameters}
        if placeholder_names != parameter_names:
            raise ReportValidationError(
                f"{path}.parameters",
                "query parameters must match SQL placeholders.",
            )
        if not isinstance(value.get("pagination", False), bool):
            raise ReportValidationError(
                f"{path}.pagination",
                "query pagination must be a boolean.",
            )
        for parameter_id, binding in parameters.items():
            binding_path = f"{path}.parameters.{parameter_id}"
            if not isinstance(binding, dict):
                raise ReportValidationError(
                    binding_path,
                    "query parameter binding must be an object.",
                )
            filter_id = binding.get("filterId")
            if not isinstance(filter_id, str) or filter_id not in filters:
                raise ReportValidationError(
                    f"{binding_path}.filterId",
                    f"filter {filter_id or '<empty>'} does not exist.",
                )
            if "valueIndex" in binding and (
                isinstance(binding["valueIndex"], bool)
                or not isinstance(binding["valueIndex"], int)
                or binding["valueIndex"] < 0
            ):
                raise ReportValidationError(
                    f"{binding_path}.valueIndex",
                    "valueIndex must be a non-negative integer.",
                )
            _require_nested_text(binding, "type", binding_path)


def _validate_charts(
    charts: dict[str, Any],
    queries: dict[str, Any],
) -> None:
    for chart_id, value in charts.items():
        path = f"charts.{chart_id}"
        if not isinstance(value, dict):
            raise ReportValidationError(path, "chart must be an object.")
        _validate_query_reference(value, queries, path)
        if not isinstance(value.get("option"), dict):
            raise ReportValidationError(
                f"{path}.option",
                "ECharts option must be an object.",
            )


def _validate_tables(
    tables: dict[str, Any],
    queries: dict[str, Any],
) -> None:
    for table_id, value in tables.items():
        path = f"tables.{table_id}"
        if not isinstance(value, dict):
            raise ReportValidationError(path, "table must be an object.")
        _validate_query_reference(value, queries, path)
        if not isinstance(value.get("options"), dict):
            raise ReportValidationError(
                f"{path}.options",
                "VTable options must be an object.",
            )


def _validate_layout(
    layout: dict[str, Any],
    filters: dict[str, Any],
    charts: dict[str, Any],
    tables: dict[str, Any],
) -> None:
    content = layout.get("content")
    zones = layout.get("zones", {})
    if not isinstance(content, list):
        raise ReportValidationError(
            "layout.content",
            "layout content must be an array.",
        )
    if not isinstance(zones, dict):
        raise ReportValidationError(
            "layout.zones",
            "layout zones must be an object.",
        )
    for index, block in enumerate(content):
        _validate_layout_block(
            block,
            f"layout.content.{index}",
            filters,
            charts,
            tables,
        )
    for zone_id, blocks in zones.items():
        zone_path = f"layout.zones.{zone_id}"
        if not isinstance(blocks, list):
            raise ReportValidationError(
                zone_path,
                "layout zone must be an array.",
            )
        for index, block in enumerate(blocks):
            _validate_layout_block(
                block,
                f"{zone_path}.{index}",
                filters,
                charts,
                tables,
            )


def _validate_layout_block(
    block: Any,
    path: str,
    filters: dict[str, Any],
    charts: dict[str, Any],
    tables: dict[str, Any],
) -> None:
    if not isinstance(block, dict):
        raise ReportValidationError(path, "layout block must be an object.")
    block_type = block.get("type")
    props = block.get("props")
    if not isinstance(block_type, str) or not block_type:
        raise ReportValidationError(f"{path}.type", "block type is required.")
    if not isinstance(props, dict):
        raise ReportValidationError(
            f"{path}.props",
            "block props must be an object.",
        )
    if block_type == "FilterBlock":
        filter_ids = props.get("filterIds")
        if not isinstance(filter_ids, list):
            raise ReportValidationError(
                f"{path}.props.filterIds",
                "filterIds must be an array.",
            )
        for index, filter_id in enumerate(filter_ids):
            if not isinstance(filter_id, str) or filter_id not in filters:
                raise ReportValidationError(
                    f"{path}.props.filterIds.{index}",
                    f"filter {filter_id or '<empty>'} does not exist.",
                )
    elif block_type == "ChartBlock":
        _validate_layout_id_reference(
            props,
            "chartId",
            charts,
            f"{path}.props",
        )
    elif block_type == "TableBlock":
        _validate_layout_id_reference(
            props,
            "tableId",
            tables,
            f"{path}.props",
        )


def _validate_query_reference(
    value: dict[str, Any],
    queries: dict[str, Any],
    path: str,
) -> None:
    query_id = value.get("queryId")
    if not isinstance(query_id, str) or query_id not in queries:
        raise ReportValidationError(
            f"{path}.queryId",
            f"query {query_id or '<empty>'} does not exist.",
        )


def _validate_layout_id_reference(
    props: dict[str, Any],
    key: str,
    definitions: dict[str, Any],
    path: str,
) -> None:
    reference = props.get(key)
    if not isinstance(reference, str) or reference not in definitions:
        raise ReportValidationError(
            f"{path}.{key}",
            f"{key} {reference or '<empty>'} does not exist.",
        )


def _require_text(payload: Mapping[str, Any], key: str) -> None:
    if not isinstance(payload.get(key), str) or not str(payload[key]).strip():
        raise ReportValidationError(key, f"{key} is required.")


def _require_nested_text(
    payload: Mapping[str, Any],
    key: str,
    path: str,
) -> None:
    if not isinstance(payload.get(key), str) or not str(payload[key]).strip():
        raise ReportValidationError(
            f"{path}.{key}",
            f"{key} is required.",
        )
