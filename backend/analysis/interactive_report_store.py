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
    dataUpdatedAt: str | None = None
    derivedFromReportId: str | None = None
    deletedAt: str | None = None


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


@dataclass(frozen=True)
class ReportShareRecord:
    reportId: str
    recipientUserId: str
    permission: str
    createdAt: str


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
            "dataUpdatedAt": str(payload.get("dataUpdatedAt") or "").strip() or None,
            "derivedFromReportId": str(payload.get("derivedFromReportId") or "").strip() or None,
            "deletedAt": None,
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

    def list_reports(self, *, user_id: str | None = None, limit: int = 50) -> list[InteractiveReportRecord]:
        reports = [_report_from_dict(item) for item in self._read_state()["reports"] if not item.get("deletedAt")]
        if user_id:
            reports = [item for item in reports if item.ownerId == user_id]
        return sorted(reports, key=lambda item: item.updatedAt, reverse=True)[:limit]

    def get_report(self, report_id: str, *, version: int | None = None) -> tuple[InteractiveReportRecord, InteractiveReportVersionRecord] | None:
        state = self._read_state()
        report = next((item for item in state["reports"] if item["id"] == report_id), None)
        if not report or report.get("deletedAt"):
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

    def rename_report(self, report_id: str, *, owner_id: str, title: str) -> InteractiveReportRecord | None:
        state = self._read_state()
        now = _now()
        updated = None
        reports = []
        for item in state["reports"]:
            if item["id"] == report_id and not item.get("deletedAt") and item.get("ownerId") == owner_id:
                updated = {**item, "title": title.strip(), "updatedAt": now}
                reports.append(updated)
            else:
                reports.append(item)
        if not updated:
            return None
        state["reports"] = reports
        self._write_state(state)
        return _report_from_dict(updated)

    def delete_report(self, report_id: str, *, owner_id: str) -> bool:
        state = self._read_state()
        now = _now()
        changed = False
        reports = []
        for item in state["reports"]:
            if item["id"] == report_id and not item.get("deletedAt") and item.get("ownerId") == owner_id:
                reports.append({**item, "deletedAt": now, "updatedAt": now})
                changed = True
            else:
                reports.append(item)
        if not changed:
            return False
        state["reports"] = reports
        state["shares"] = [share for share in state["shares"] if share.get("reportId") != report_id]
        self._write_state(state)
        return True

    def share_report(self, report_id: str, *, owner_id: str, recipient_user_id: str, permission: str) -> ReportShareRecord | None:
        if permission not in {"view", "view_and_reuse"}:
            raise ValueError("invalid_report_share_permission")
        state = self._read_state()
        report = next((item for item in state["reports"] if item["id"] == report_id and not item.get("deletedAt")), None)
        if not report or report.get("ownerId") != owner_id:
            return None
        now = _now()
        share = {
            "reportId": report_id,
            "recipientUserId": recipient_user_id.strip(),
            "permission": permission,
            "createdAt": now,
        }
        state["shares"] = [
            item for item in state["shares"]
            if not (item.get("reportId") == report_id and item.get("recipientUserId") == recipient_user_id.strip())
        ]
        state["shares"].append(share)
        self._write_state(state)
        return _share_from_dict(share)

    def revoke_report_share(self, report_id: str, *, owner_id: str, recipient_user_id: str) -> bool:
        state = self._read_state()
        report = next((item for item in state["reports"] if item["id"] == report_id and not item.get("deletedAt")), None)
        if not report or report.get("ownerId") != owner_id:
            return False
        before = len(state["shares"])
        state["shares"] = [
            item for item in state["shares"]
            if not (item.get("reportId") == report_id and item.get("recipientUserId") == recipient_user_id)
        ]
        if len(state["shares"]) == before:
            return False
        self._write_state(state)
        return True

    def list_report_center(self, *, user_id: str, limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        state = self._read_state()
        reports_by_id = {item["id"]: item for item in state["reports"] if not item.get("deletedAt")}
        mine = [_report_from_dict(item) for item in reports_by_id.values() if item.get("ownerId") == user_id]
        shared = []
        for share in state["shares"]:
            if share.get("recipientUserId") != user_id:
                continue
            report = reports_by_id.get(str(share.get("reportId")))
            if not report:
                continue
            shared.append({"share": _share_from_dict(share), "report": _report_from_dict(report)})
        mine = sorted(mine, key=lambda item: item.updatedAt, reverse=True)[:limit]
        shared = sorted(shared, key=lambda item: item["report"].updatedAt, reverse=True)[:limit]
        return {
            "mine": [{"report": asdict_report(report)} for report in mine],
            "sharedWithMe": [
                {**asdict_share(item["share"]), "report": asdict_report(item["report"])}
                for item in shared
            ],
        }

    def _read_state(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"reports": [], "versions": [], "shares": []}
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
        shares = list(payload.get("shares") or [])
        return {"reports": reports, "versions": versions, "shares": shares}

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
    for name in ("dataUpdatedAt", "derivedFromReportId"):
        if name in payload and payload.get(name) is not None and not isinstance(payload.get(name), str):
            raise ValueError(f"{name} has an invalid type.")


def _report_from_dict(payload: dict[str, Any]) -> InteractiveReportRecord:
    return InteractiveReportRecord(**_filter_dataclass_payload(payload, InteractiveReportRecord))


def _version_from_dict(payload: dict[str, Any]) -> InteractiveReportVersionRecord:
    return InteractiveReportVersionRecord(**_filter_dataclass_payload(payload, InteractiveReportVersionRecord))


def _share_from_dict(payload: dict[str, Any]) -> ReportShareRecord:
    return ReportShareRecord(**_filter_dataclass_payload(payload, ReportShareRecord))


def asdict_report(record: InteractiveReportRecord) -> dict[str, Any]:
    return {key: value for key, value in _record_asdict(record).items() if value is not None}


def asdict_share(record: ReportShareRecord) -> dict[str, Any]:
    return _record_asdict(record)


def _record_asdict(record: Any) -> dict[str, Any]:
    return {field.name: getattr(record, field.name) for field in fields(record)}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _filter_dataclass_payload(payload: dict[str, Any], target: type[Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(target)}
    return {key: value for key, value in payload.items() if key in allowed}
