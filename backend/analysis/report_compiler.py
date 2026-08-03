from __future__ import annotations

from hashlib import sha1
from typing import Any

from backend.analysis.report_artifact import normalize_report_artifact


def compile_interactive_report(payload: dict[str, Any], *, thread_id: str, turn_id: str) -> dict[str, Any]:
    title = _text(payload.get("title")) or "渠道销售占比分析"
    source_text = _text(payload.get("sourceTable") or payload.get("sourceDescription") or payload.get("source"))
    subtitle = _text(payload.get("subtitle")) or "基于本轮已查证数据生成"
    dataset_id = _text(payload.get("datasetId") or payload.get("dataset_id")) or "channel_sales"
    rows = _rows(payload.get("rows") or payload.get("dataset") or payload.get("data"))
    report_id = _text(payload.get("id")) or f"report_{sha1((thread_id + turn_id + title).encode('utf-8')).hexdigest()[:12]}"

    report = {
        "artifactType": "interactive_report",
        "schemaVersion": "1.0",
        "id": report_id,
        "title": title,
        "subtitle": subtitle,
        "renderer": "puck",
        "document": {
            "root": {"props": {"title": title}},
            "content": [
                {"type": "SectionBlock", "props": {"id": f"{report_id}-section-summary", "title": "本期结论", "tone": "coral"}},
                {"type": "MarkdownBlock", "props": {"id": f"{report_id}-summary", "content": _text(payload.get("summary")) or "已根据真实查询结果生成最小交互式报告。"}},
                {"type": "SectionBlock", "props": {"id": f"{report_id}-section-channel", "title": "渠道贡献", "tone": "navy"}},
                {"type": "ChartBlock", "props": {"id": f"{report_id}-chart", "chartSpecRef": "channel-sales-chart", "queryRef": "channel-sales-query"}},
                {"type": "GridBlock", "props": {"id": f"{report_id}-grid", "gridSpecRef": "channel-sales-grid", "queryRef": "channel-sales-query"}},
                {"type": "EvidenceBlock", "props": {"id": f"{report_id}-evidence", "label": "数据来源", "content": source_text or "本轮已查证数据集"}},
            ],
            "zones": {},
        },
        "filters": [],
        "queries": {
            "channel-sales-query": {
                "datasetId": dataset_id,
                "filterBindings": [],
            }
        },
        "chartSpecs": {
            "channel-sales-chart": {
                "id": "channel-sales-chart",
                "datasetId": dataset_id,
                "type": "bar",
                "xField": _first_present_field(rows, ["channel", "vchannel_name", "vchannel_type", "渠道"], "channel"),
                "title": "渠道销售额",
                "series": [
                    {
                        "field": _first_present_field(rows, ["salesAmount", "sales_amount", "gmv", "销售额"], "salesAmount"),
                        "label": "销售额",
                        "format": "currency",
                    }
                ],
            }
        },
        "gridSpecs": {
            "channel-sales-grid": {
                "id": "channel-sales-grid",
                "datasetId": dataset_id,
                "columns": _grid_columns(rows),
                "pageSize": 10,
            }
        },
        "datasets": {
            dataset_id: {
                "rows": rows,
            }
        },
        "source": {
            "threadId": thread_id,
            "turnId": turn_id,
        },
        "ownerId": _text(payload.get("ownerId")) or "codex-agent",
    }
    return normalize_report_artifact(report)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _first_present_field(rows: list[dict[str, Any]], candidates: list[str], fallback: str) -> str:
    fields = set().union(*(row.keys() for row in rows)) if rows else set()
    return next((field for field in candidates if field in fields), fallback)


def _grid_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return [
            {"field": "channel", "label": "渠道"},
            {"field": "salesAmount", "label": "销售额", "format": "currency"},
            {"field": "salesShare", "label": "占比", "format": "percent"},
        ]
    return [
        {"field": field, "label": _column_label(field), **({"format": _column_format(field)} if _column_format(field) else {})}
        for field in rows[0].keys()
    ]


def _column_label(field: str) -> str:
    labels = {
        "channel": "渠道",
        "vchannel_name": "渠道",
        "vchannel_type": "渠道类型",
        "salesAmount": "销售额",
        "sales_amount": "销售额",
        "salesShare": "占比",
        "sales_share": "占比",
        "gmv": "GMV",
    }
    return labels.get(field, field)


def _column_format(field: str) -> str | None:
    lowered = field.lower()
    if "share" in lowered or "rate" in lowered or "占比" in field:
        return "percent"
    if "amount" in lowered or "sales" in lowered or "gmv" in lowered or "销售额" in field:
        return "currency"
    return None
