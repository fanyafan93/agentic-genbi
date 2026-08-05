from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class ReportRecord:
    id: str
    title: str
    subtitle: str
    ownerId: str
    turnId: str | None
    layout: dict[str, Any]
    filters: dict[str, Any]
    charts: dict[str, Any]
    tables: dict[str, Any]
    queries: dict[str, Any]
    createdAt: str
    updatedAt: str


@dataclass(frozen=True)
class ReportShareRecord:
    reportId: str
    recipientUserId: str
    permission: str
    createdAt: str


def report_to_payload(
    record: ReportRecord,
    *,
    source_session_id: str | None = None,
) -> dict[str, Any]:
    payload = _record_to_dict(record)
    if source_session_id:
        payload["sourceSessionId"] = source_session_id
    return payload


def share_to_payload(record: ReportShareRecord) -> dict[str, Any]:
    return _record_to_dict(record)


def report_from_payload(payload: dict[str, Any]) -> ReportRecord:
    return ReportRecord(**_filter_record_fields(payload, ReportRecord))


def share_from_payload(payload: dict[str, Any]) -> ReportShareRecord:
    return ReportShareRecord(**_filter_record_fields(payload, ReportShareRecord))


def _record_to_dict(record: Any) -> dict[str, Any]:
    return {field.name: getattr(record, field.name) for field in fields(record)}


def _filter_record_fields(
    payload: dict[str, Any],
    record_type: type[Any],
) -> dict[str, Any]:
    allowed = {field.name for field in fields(record_type)}
    return {key: value for key, value in payload.items() if key in allowed}
