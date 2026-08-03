from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_INTERACTIVE_REPORT_STORE_PATH = Path(".resource-index/interactive-reports.json")


class InteractiveReportVersionConflict(ValueError):
    pass


@dataclass(frozen=True)
class InteractiveReportRecord:
    id: str
    title: str
    subtitle: str
    artifactType: str
    renderer: str
    ownerId: str
    sourceThreadId: str
    sourceTurnId: str
    latestVersion: int
    createdAt: str
    updatedAt: str


@dataclass(frozen=True)
class InteractiveReportVersionRecord:
    reportId: str
    version: int
    sourceThreadId: str
    sourceTurnId: str
    document: dict[str, Any]
    filters: list[dict[str, Any]]
    queries: dict[str, Any]
    chartSpecs: dict[str, Any]
    gridSpecs: dict[str, Any]
    createdAt: str
    datasets: dict[str, Any] = field(default_factory=dict)


class InteractiveReportStore:
    """Development fallback for interactive reports when Postgres is unavailable."""

    def __init__(self, path: Path = DEFAULT_INTERACTIVE_REPORT_STORE_PATH) -> None:
        self.path = path

    def save_report(self, payload: dict[str, Any]) -> tuple[InteractiveReportRecord, InteractiveReportVersionRecord]:
        _validate_payload(payload)
        state = self._read_state()
        report_id = str(payload["id"]).strip()
        existing = next((item for item in state["reports"] if item["id"] == report_id), None)
        current_version = int(existing["latestVersion"]) if existing else 0
        expected_version = payload.get("expectedVersion")
        if existing and expected_version != current_version:
            raise InteractiveReportVersionConflict("interactive_report_version_conflict")
        if not existing and expected_version not in (None, 0):
            raise InteractiveReportVersionConflict("interactive_report_version_conflict")

        now = _now()
        version_number = current_version + 1
        report = {
            "id": report_id,
            "title": str(payload["title"]).strip(),
            "subtitle": str(payload["subtitle"]).strip(),
            "artifactType": str(payload["artifactType"]).strip(),
            "renderer": str(payload["renderer"]).strip(),
            "ownerId": str(payload["ownerId"]).strip(),
            "sourceThreadId": str(payload["source"]["threadId"]).strip(),
            "sourceTurnId": str(payload["source"]["turnId"]).strip(),
            "latestVersion": version_number,
            "createdAt": existing["createdAt"] if existing else now,
            "updatedAt": now,
        }
        version = {
            "reportId": report_id,
            "version": version_number,
            "sourceThreadId": str(payload["source"]["threadId"]).strip(),
            "sourceTurnId": str(payload["source"]["turnId"]).strip(),
            "document": payload["document"],
            "filters": payload["filters"],
            "queries": payload["queries"],
            "chartSpecs": payload["chartSpecs"],
            "gridSpecs": payload["gridSpecs"],
            "datasets": payload.get("datasets", {}),
            "createdAt": now,
        }
        state["reports"] = [item for item in state["reports"] if item["id"] != report_id]
        state["reports"].append(report)
        state["versions"].append(version)
        self._write_state(state)
        return _report_from_dict(report), _version_from_dict(version)

    def list_reports(self, *, owner_id: str | None = None, limit: int = 50) -> list[InteractiveReportRecord]:
        reports = [_report_from_dict(item) for item in self._read_state()["reports"]]
        if owner_id:
            reports = [item for item in reports if item.ownerId == owner_id]
        return sorted(reports, key=lambda item: item.updatedAt, reverse=True)[:limit]

    def get_report(self, report_id: str, *, version: int | None = None) -> tuple[InteractiveReportRecord, InteractiveReportVersionRecord] | None:
        state = self._read_state()
        report = next((item for item in state["reports"] if item["id"] == report_id), None)
        if not report:
            return None
        target_version = version if version is not None else int(report["latestVersion"])
        record = next((item for item in state["versions"] if item["reportId"] == report_id and int(item["version"]) == target_version), None)
        return (_report_from_dict(report), _version_from_dict(record)) if record else None

    def list_versions(self, report_id: str) -> list[InteractiveReportVersionRecord] | None:
        state = self._read_state()
        if not any(item["id"] == report_id for item in state["reports"]):
            return None
        records = [_version_from_dict(item) for item in state["versions"] if item["reportId"] == report_id]
        return sorted(records, key=lambda item: item.version, reverse=True)

    def _read_state(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"reports": [], "versions": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        reports = list(payload.get("reports") or [])
        sources = {
            str(report.get("id")): {
                "sourceThreadId": report.get("sourceThreadId", ""),
                "sourceTurnId": report.get("sourceTurnId", ""),
            }
            for report in reports
        }
        versions = []
        for version in list(payload.get("versions") or []):
            normalized = dict(version)
            for name, value in sources.get(str(normalized.get("reportId")), {}).items():
                normalized.setdefault(name, value)
            versions.append(normalized)
        return {"reports": reports, "versions": versions}

    def _write_state(self, state: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _validate_payload(payload: dict[str, Any]) -> None:
    for name in ("id", "title", "subtitle", "artifactType", "renderer", "ownerId"):
        if not str(payload.get(name) or "").strip():
            raise ValueError(f"{name} is required.")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ValueError("source is required.")
    for name in ("threadId", "turnId"):
        if not str(source.get(name) or "").strip():
            raise ValueError(f"source.{name} is required.")
    if not isinstance(payload.get("document"), dict):
        raise ValueError("document must be an object.")
    for name, expected in (("filters", list), ("queries", dict), ("chartSpecs", dict), ("gridSpecs", dict)):
        if not isinstance(payload.get(name), expected):
            raise ValueError(f"{name} has an invalid type.")
    if "datasets" in payload and not isinstance(payload.get("datasets"), dict):
        raise ValueError("datasets has an invalid type.")


def _report_from_dict(payload: dict[str, Any]) -> InteractiveReportRecord:
    return InteractiveReportRecord(**_filter_dataclass_payload(payload, InteractiveReportRecord))


def _version_from_dict(payload: dict[str, Any]) -> InteractiveReportVersionRecord:
    return InteractiveReportVersionRecord(**_filter_dataclass_payload(payload, InteractiveReportVersionRecord))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _filter_dataclass_payload(payload: dict[str, Any], target: type[Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(target)}
    return {key: value for key, value in payload.items() if key in allowed}
