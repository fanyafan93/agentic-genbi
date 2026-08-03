from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ReportArtifactIssue:
    path: str
    message: str
    code: str = "invalid"


def validate_report_artifact(artifact: dict[str, Any]) -> list[ReportArtifactIssue]:
    issues: list[ReportArtifactIssue] = []
    _require_text(artifact, "id", issues)
    _require_text(artifact, "title", issues)
    _require_text(artifact, "subtitle", issues)
    if artifact.get("artifactType") != "interactive_report":
        issues.append(ReportArtifactIssue("artifactType", "artifactType must be interactive_report.", "unsupported_artifact_type"))
    if artifact.get("renderer") != "puck":
        issues.append(ReportArtifactIssue("renderer", "renderer must be puck.", "unsupported_renderer"))

    datasets = artifact.get("datasets")
    queries = artifact.get("queries")
    chart_specs = artifact.get("chartSpecs")
    grid_specs = artifact.get("gridSpecs")
    document = artifact.get("document")

    if not isinstance(datasets, dict) or not datasets:
        issues.append(ReportArtifactIssue("datasets", "datasets must be a non-empty object.", "missing_datasets"))
        datasets = {}
    if not isinstance(queries, dict):
        issues.append(ReportArtifactIssue("queries", "queries must be an object.", "invalid_queries"))
        queries = {}
    if not isinstance(chart_specs, dict):
        issues.append(ReportArtifactIssue("chartSpecs", "chartSpecs must be an object.", "invalid_chart_specs"))
        chart_specs = {}
    if not isinstance(grid_specs, dict):
        issues.append(ReportArtifactIssue("gridSpecs", "gridSpecs must be an object.", "invalid_grid_specs"))
        grid_specs = {}
    if not isinstance(document, dict):
        issues.append(ReportArtifactIssue("document", "document must be an object.", "invalid_document"))

    dataset_fields = {dataset_id: _dataset_fields(dataset) for dataset_id, dataset in datasets.items() if isinstance(dataset, dict)}
    for dataset_id, fields in dataset_fields.items():
        if not fields:
            issues.append(ReportArtifactIssue(f"datasets.{dataset_id}.rows", "dataset must contain rows or columns.", "empty_dataset"))

    for query_id, query in queries.items():
        if not isinstance(query, dict):
            issues.append(ReportArtifactIssue(f"queries.{query_id}", "query must be an object.", "invalid_query"))
            continue
        dataset_id = str(query.get("datasetId") or "")
        if dataset_id not in datasets:
            issues.append(ReportArtifactIssue(f"queries.{query_id}.datasetId", f"dataset {dataset_id or '<empty>'} does not exist.", "missing_dataset"))

    for chart_id, spec in chart_specs.items():
        if not isinstance(spec, dict):
            issues.append(ReportArtifactIssue(f"chartSpecs.{chart_id}", "chart spec must be an object.", "invalid_chart_spec"))
            continue
        dataset_id = str(spec.get("datasetId") or "")
        fields = dataset_fields.get(dataset_id, set())
        if not fields:
            issues.append(ReportArtifactIssue(f"chartSpecs.{chart_id}.datasetId", f"dataset {dataset_id or '<empty>'} does not exist or has no fields.", "missing_dataset"))
            continue
        x_field = str(spec.get("xField") or "")
        if x_field not in fields:
            issues.append(ReportArtifactIssue(f"chartSpecs.{chart_id}.xField", f"field {x_field or '<empty>'} not found in dataset {dataset_id}.", "missing_field"))
        series = spec.get("series")
        if not isinstance(series, list) or not series:
            issues.append(ReportArtifactIssue(f"chartSpecs.{chart_id}.series", "chart series must be a non-empty array.", "missing_series"))
            continue
        for index, item in enumerate(series):
            field = str(item.get("field") or "") if isinstance(item, dict) else ""
            if field not in fields:
                issues.append(ReportArtifactIssue(f"chartSpecs.{chart_id}.series.{index}.field", f"field {field or '<empty>'} not found in dataset {dataset_id}.", "missing_field"))

    for grid_id, spec in grid_specs.items():
        if not isinstance(spec, dict):
            issues.append(ReportArtifactIssue(f"gridSpecs.{grid_id}", "grid spec must be an object.", "invalid_grid_spec"))
            continue
        dataset_id = str(spec.get("datasetId") or "")
        fields = dataset_fields.get(dataset_id, set())
        if not fields:
            issues.append(ReportArtifactIssue(f"gridSpecs.{grid_id}.datasetId", f"dataset {dataset_id or '<empty>'} does not exist or has no fields.", "missing_dataset"))
            continue
        columns = spec.get("columns")
        if not isinstance(columns, list) or not columns:
            issues.append(ReportArtifactIssue(f"gridSpecs.{grid_id}.columns", "grid columns must be a non-empty array.", "missing_columns"))
            continue
        for index, column in enumerate(columns):
            field = str(column.get("field") or "") if isinstance(column, dict) else ""
            if field not in fields:
                issues.append(ReportArtifactIssue(f"gridSpecs.{grid_id}.columns.{index}.field", f"field {field or '<empty>'} not found in dataset {dataset_id}.", "missing_field"))

    return issues


def normalize_report_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(artifact)
    datasets = normalized.get("datasets")
    if not isinstance(datasets, dict):
        return normalized
    dataset_fields = {dataset_id: _dataset_fields(dataset) for dataset_id, dataset in datasets.items() if isinstance(dataset, dict)}
    normalized["chartSpecs"] = _normalize_chart_specs(normalized.get("chartSpecs"), dataset_fields)
    normalized["gridSpecs"] = _normalize_grid_specs(normalized.get("gridSpecs"), dataset_fields)
    return normalized


def issues_to_payload(issues: list[ReportArtifactIssue]) -> list[dict[str, str]]:
    return [asdict(issue) for issue in issues]


def _normalize_chart_specs(value: Any, dataset_fields: dict[str, set[str]]) -> Any:
    if not isinstance(value, dict):
        return value
    next_specs: dict[str, Any] = {}
    for chart_id, spec in value.items():
        if not isinstance(spec, dict):
            next_specs[chart_id] = spec
            continue
        next_spec = dict(spec)
        fields = dataset_fields.get(str(next_spec.get("datasetId") or ""), set())
        rows_fields = list(fields)
        if next_spec.get("xField") not in fields:
            next_spec["xField"] = _best_dimension_field(rows_fields, str(next_spec.get("xField") or ""))
        series = []
        for item in next_spec.get("series") if isinstance(next_spec.get("series"), list) else []:
            next_item = dict(item) if isinstance(item, dict) else {}
            if next_item.get("field") not in fields:
                next_item["field"] = _best_measure_field(rows_fields, str(next_item.get("field") or ""))
            series.append(next_item)
        next_spec["series"] = series
        next_specs[chart_id] = next_spec
    return next_specs


def _normalize_grid_specs(value: Any, dataset_fields: dict[str, set[str]]) -> Any:
    if not isinstance(value, dict):
        return value
    next_specs: dict[str, Any] = {}
    for grid_id, spec in value.items():
        if not isinstance(spec, dict):
            next_specs[grid_id] = spec
            continue
        next_spec = dict(spec)
        fields = dataset_fields.get(str(next_spec.get("datasetId") or ""), set())
        columns = next_spec.get("columns")
        if isinstance(columns, list):
            next_spec["columns"] = [column for column in columns if isinstance(column, dict) and column.get("field") in fields]
        if not next_spec.get("columns"):
            next_spec["columns"] = [{"field": field, "label": field} for field in fields]
        next_specs[grid_id] = next_spec
    return next_specs


def _dataset_fields(dataset: dict[str, Any]) -> set[str]:
    fields: set[str] = set()
    columns = dataset.get("columns")
    if isinstance(columns, list):
        fields.update(str(column.get("field")) for column in columns if isinstance(column, dict) and column.get("field"))
    rows = dataset.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                fields.update(str(key) for key in row.keys())
    return fields


def _best_dimension_field(fields: list[str], requested: str) -> str:
    for candidate in (requested, "channel", "vchannel_name", "month", "vmonth_code", "date", "name", "category", "渠道", "月份", "名称"):
        if candidate in fields:
            return candidate
    for field in fields:
        lowered = field.lower()
        if any(token in lowered for token in ("channel", "month", "date", "name", "category")) or any(token in field for token in ("渠道", "月份", "日期", "名称")):
            return field
    return fields[0] if fields else requested


def _best_measure_field(fields: list[str], requested: str) -> str:
    for candidate in (requested, "salesAmount", "sales_amt", "sales_amount", "gmv", "value", "amount", "销售额", "数值"):
        if candidate in fields:
            return candidate
    for field in fields:
        lowered = field.lower()
        if any(token in lowered for token in ("sales", "amount", "gmv", "revenue", "value", "qty")) or any(token in field for token in ("销售", "金额", "数值", "数量")):
            return field
    return fields[0] if fields else requested


def _require_text(payload: dict[str, Any], key: str, issues: list[ReportArtifactIssue]) -> None:
    if not str(payload.get(key) or "").strip():
        issues.append(ReportArtifactIssue(key, f"{key} is required.", "required"))
