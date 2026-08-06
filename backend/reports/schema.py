from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.reports.build_models import ReportValidationIssue
from backend.reports.query_service import (
    PARAMETER_NAME,
    UnsafeReportQuery,
    query_parameter_names,
)


FILTER_TYPES = {"select", "multiSelect", "date", "dateRange"}
REPORT_DATA_SOURCES = {"doris", "mysql"}
EXPORT_COLUMN_TYPES = {
    "text",
    "number",
    "date",
    "datetime",
    "boolean",
}
LAYOUT_BLOCK_TYPES = {
    "FilterBlock",
    "ChartBlock",
    "TableBlock",
    "SectionBlock",
    "MarkdownBlock",
}
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


def collect_report_validation_errors(
    report: Mapping[str, Any],
) -> list[ReportValidationIssue]:
    issues: list[ReportValidationIssue] = []
    seen_paths: set[str] = set()

    def collect(validation: Callable[[], None]) -> None:
        try:
            validation()
        except ReportValidationError as exc:
            if exc.path in seen_paths:
                return
            seen_paths.add(exc.path)
            issues.append(
                ReportValidationIssue(
                    path=exc.path,
                    code=_validation_issue_code(exc),
                    message=exc.message,
                )
            )

    if not isinstance(report, Mapping):
        return [
            ReportValidationIssue(
                path="report",
                code="invalid_type",
                message="report must be an object.",
            )
        ]

    for key in sorted(LEGACY_REPORT_FIELDS):
        if key in report:
            collect(
                lambda key=key: _raise_validation_error(
                    key,
                    f"{key} is not part of the Report contract.",
                )
            )
    for key in ("title", "subtitle"):
        collect(lambda key=key: _require_text(report, key))

    sections: dict[str, dict[str, Any]] = {}
    for key in ("layout", "filters", "charts", "tables", "queries"):
        value = report.get(key)
        if not isinstance(value, dict):
            collect(
                lambda key=key: _raise_validation_error(
                    key,
                    f"{key} must be an object.",
                )
            )
            sections[key] = {}
        else:
            sections[key] = value

    filters = sections["filters"]
    queries = sections["queries"]
    charts = sections["charts"]
    tables = sections["tables"]
    layout = sections["layout"]

    for filter_id in sorted(filters, key=str):
        collect(
            lambda filter_id=filter_id: _validate_filters(
                {filter_id: filters[filter_id]}
            )
        )
    for query_id in sorted(queries, key=str):
        collect(
            lambda query_id=query_id: _validate_queries(
                {query_id: queries[query_id]},
                filters,
            )
        )
    for chart_id in sorted(charts, key=str):
        collect(
            lambda chart_id=chart_id: _validate_charts(
                {chart_id: charts[chart_id]},
                queries,
            )
        )
    for table_id in sorted(tables, key=str):
        collect(
            lambda table_id=table_id: _validate_tables(
                {table_id: tables[table_id]},
                queries,
            )
        )
    _collect_layout_validation_errors(
        layout,
        filters,
        charts,
        tables,
        collect,
    )
    return issues


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


def _collect_layout_validation_errors(
    layout: dict[str, Any],
    filters: dict[str, Any],
    charts: dict[str, Any],
    tables: dict[str, Any],
    collect: Callable[[Callable[[], None]], None],
) -> None:
    content = layout.get("content")
    zones = layout.get("zones", {})
    if not isinstance(content, list):
        collect(
            lambda: _raise_validation_error(
                "layout.content",
                "layout content must be an array.",
            )
        )
    else:
        for index, block in enumerate(content):
            collect(
                lambda index=index, block=block: _validate_layout_block(
                    block,
                    f"layout.content.{index}",
                    filters,
                    charts,
                    tables,
                )
            )
    if not isinstance(zones, dict):
        collect(
            lambda: _raise_validation_error(
                "layout.zones",
                "layout zones must be an object.",
            )
        )
        return
    for zone_id in sorted(zones, key=str):
        blocks = zones[zone_id]
        zone_path = f"layout.zones.{zone_id}"
        if not isinstance(blocks, list):
            collect(
                lambda zone_path=zone_path: _raise_validation_error(
                    zone_path,
                    "layout zone must be an array.",
                )
            )
            continue
        for index, block in enumerate(blocks):
            collect(
                lambda index=index, block=block, zone_path=zone_path:
                    _validate_layout_block(
                        block,
                        f"{zone_path}.{index}",
                        filters,
                        charts,
                        tables,
                    )
            )


def _raise_validation_error(path: str, message: str) -> None:
    raise ReportValidationError(path, message)


def _validation_issue_code(error: ReportValidationError) -> str:
    message = error.message.lower()
    if "does not exist" in message:
        return "invalid_reference"
    if "required" in message:
        return "required"
    if "must be" in message:
        return "invalid_type"
    if "not part of" in message:
        return "unsupported_field"
    return "invalid_value"


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
        data_source = str(value["dataSource"]).strip().lower()
        if data_source not in REPORT_DATA_SOURCES:
            raise ReportValidationError(
                f"{path}.dataSource",
                (
                    "query dataSource must be one of "
                    f"{sorted(REPORT_DATA_SOURCES)}."
                ),
            )
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
        _validate_query_controls(value.get("controls"), path)
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


def _validate_query_controls(controls: Any, path: str) -> None:
    if controls is None:
        return
    controls_path = f"{path}.controls"
    if not isinstance(controls, dict):
        raise ReportValidationError(
            controls_path,
            "query controls must be an object.",
        )
    for key in ("sortableFields", "filterableFields"):
        fields = controls.get(key, [])
        fields_path = f"{controls_path}.{key}"
        if not isinstance(fields, list):
            raise ReportValidationError(
                fields_path,
                f"{key} must be an array.",
            )
        for index, field in enumerate(fields):
            if (
                not isinstance(field, str)
                or not PARAMETER_NAME.fullmatch(field)
            ):
                raise ReportValidationError(
                    f"{fields_path}.{index}",
                    "query control field must be a safe SQL identifier.",
                )


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
        if not isinstance(value["option"].get("series"), list):
            raise ReportValidationError(
                f"{path}.option.series",
                "ECharts option series must be an array.",
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
        if not isinstance(value["options"].get("columns"), list):
            raise ReportValidationError(
                f"{path}.options.columns",
                "VTable columns must be an array.",
            )
        table_type = value.get("type", "list")
        if table_type not in {"list", "pivot"}:
            raise ReportValidationError(
                f"{path}.type",
                "table type must be list or pivot.",
            )
        export_columns = value.get("exportColumns")
        if export_columns is None:
            continue
        if table_type != "list":
            raise ReportValidationError(
                f"{path}.exportColumns",
                "exportColumns are only supported for list tables.",
            )
        if not isinstance(export_columns, list) or not export_columns:
            raise ReportValidationError(
                f"{path}.exportColumns",
                "exportColumns must be a non-empty array.",
            )
        for index, column in enumerate(export_columns):
            column_path = f"{path}.exportColumns.{index}"
            if not isinstance(column, dict):
                raise ReportValidationError(
                    column_path,
                    "export column must be an object.",
                )
            field = column.get("field")
            if (
                not isinstance(field, str)
                or not PARAMETER_NAME.fullmatch(field)
            ):
                raise ReportValidationError(
                    f"{column_path}.field",
                    "export column field must be a safe SQL identifier.",
                )
            _require_nested_text(column, "title", column_path)
            column_type = column.get("type", "text")
            if column_type not in EXPORT_COLUMN_TYPES:
                raise ReportValidationError(
                    f"{column_path}.type",
                    "export column type must be one of "
                    f"{sorted(EXPORT_COLUMN_TYPES)}.",
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
    if block_type not in LAYOUT_BLOCK_TYPES:
        raise ReportValidationError(
            f"{path}.type",
            "block type must be one of "
            f"{sorted(LAYOUT_BLOCK_TYPES)}.",
        )
    if not isinstance(props, dict):
        raise ReportValidationError(
            f"{path}.props",
            "block props must be an object.",
        )
    _require_nested_text(props, "id", f"{path}.props")
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
    elif block_type == "SectionBlock":
        _require_nested_text(props, "title", f"{path}.props")
    elif block_type == "MarkdownBlock":
        _require_nested_text(props, "content", f"{path}.props")


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
