from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.reports.models import (
    ReportRecord,
    ReportShareRecord,
    report_from_payload,
    report_to_payload,
    share_from_payload,
    share_to_payload,
)
from backend.reports.schema import report_config_payload


DEFAULT_REPORT_STORE_PATH = Path(".resource-index/reports.json")
REPORT_SHARE_PERMISSIONS = {"view", "view_and_reuse"}


class ReportStore:
    """JSON development fallback for the direct Report contract."""

    def __init__(self, path: Path = DEFAULT_REPORT_STORE_PATH) -> None:
        self.path = path

    def create_report(
        self,
        config: dict[str, Any],
        *,
        owner_id: str,
        turn_id: str | None = None,
        report_id: str | None = None,
    ) -> ReportRecord:
        normalized = report_config_payload(config)
        owner = _required_text(owner_id, "owner_id")
        identifier = (
            _required_text(report_id, "report_id")
            if report_id is not None
            else f"report_{uuid4().hex}"
        )
        state = self._read_state()
        if any(item.get("id") == identifier for item in state["reports"]):
            raise ValueError("report_already_exists")
        now = _now()
        report = {
            "id": identifier,
            **normalized,
            "ownerId": owner,
            "turnId": _optional_text(turn_id),
            "createdAt": now,
            "updatedAt": now,
            "isExample": False,
        }
        state["reports"].append(report)
        self._write_state(state)
        return report_from_payload(report)

    def update_report(
        self,
        report_id: str,
        config: dict[str, Any],
        *,
        owner_id: str,
        turn_id: str | None = None,
    ) -> ReportRecord | None:
        normalized = report_config_payload(config)
        identifier = _required_text(report_id, "report_id")
        owner = _required_text(owner_id, "owner_id")
        state = self._read_state()
        existing = next(
            (
                item
                for item in state["reports"]
                if item.get("id") == identifier
                and item.get("ownerId") == owner
                and not item.get("deletedAt")
            ),
            None,
        )
        if existing is None:
            return None
        updated = {
            "id": identifier,
            **normalized,
            "ownerId": str(existing["ownerId"]),
            "turnId": (
                _optional_text(turn_id)
                if turn_id is not None
                else existing.get("turnId")
            ),
            "createdAt": str(existing["createdAt"]),
            "updatedAt": _now(),
            "isExample": bool(existing.get("isExample")),
        }
        state["reports"] = [
            updated if item.get("id") == identifier else item
            for item in state["reports"]
        ]
        self._write_state(state)
        return report_from_payload(updated)

    def list_reports(
        self,
        *,
        owner_id: str | None = None,
        turn_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[ReportRecord]:
        reports = [
            report_from_payload(item)
            for item in self._read_state()["reports"]
            if not item.get("deletedAt")
        ]
        if owner_id:
            reports = [
                report for report in reports if report.ownerId == owner_id
            ]
        if turn_ids is not None:
            reports = [
                report
                for report in reports
                if report.turnId is not None and report.turnId in turn_ids
            ]
        reports.sort(key=lambda report: report.updatedAt, reverse=True)
        return reports[:limit]

    def get_report(self, report_id: str) -> ReportRecord | None:
        identifier = _required_text(report_id, "report_id")
        report = next(
            (
                item
                for item in self._read_state()["reports"]
                if item.get("id") == identifier
                and not item.get("deletedAt")
            ),
            None,
        )
        return report_from_payload(report) if report else None

    def delete_report(self, report_id: str, *, owner_id: str) -> bool:
        identifier = _required_text(report_id, "report_id")
        owner = _required_text(owner_id, "owner_id")
        state = self._read_state()
        report = next(
            (
                item
                for item in state["reports"]
                if item.get("id") == identifier
                and item.get("ownerId") == owner
            ),
            None,
        )
        if report is None:
            return False
        if not report.get("deletedAt"):
            report["deletedAt"] = _now()
            self._write_state(state)
        return True

    def set_report_example(
        self,
        report_id: str,
        *,
        owner_id: str,
        is_example: bool,
    ) -> ReportRecord | None:
        identifier = _required_text(report_id, "report_id")
        owner = _required_text(owner_id, "owner_id")
        state = self._read_state()
        report = next(
            (
                item
                for item in state["reports"]
                if item.get("id") == identifier
                and item.get("ownerId") == owner
                and not item.get("deletedAt")
            ),
            None,
        )
        if report is None:
            return None
        report["isExample"] = bool(is_example)
        report["updatedAt"] = _now()
        self._write_state(state)
        return report_from_payload(report)

    def share_report(
        self,
        report_id: str,
        *,
        owner_id: str,
        recipient_user_id: str,
        permission: str,
    ) -> ReportShareRecord | None:
        if permission not in REPORT_SHARE_PERMISSIONS:
            raise ValueError("invalid_report_share_permission")
        identifier = _required_text(report_id, "report_id")
        owner = _required_text(owner_id, "owner_id")
        recipient = _required_text(
            recipient_user_id,
            "recipient_user_id",
        )
        state = self._read_state()
        report = next(
            (
                item
                for item in state["reports"]
                if item.get("id") == identifier
                and item.get("ownerId") == owner
                and not item.get("deletedAt")
            ),
            None,
        )
        if report is None:
            return None
        share = {
            "reportId": identifier,
            "recipientUserId": recipient,
            "permission": permission,
            "createdAt": _now(),
        }
        state["shares"] = [
            item
            for item in state["shares"]
            if not (
                item.get("reportId") == identifier
                and item.get("recipientUserId") == recipient
            )
        ]
        state["shares"].append(share)
        self._write_state(state)
        return share_from_payload(share)

    def revoke_report_share(
        self,
        report_id: str,
        *,
        owner_id: str,
        recipient_user_id: str,
    ) -> bool:
        identifier = _required_text(report_id, "report_id")
        owner = _required_text(owner_id, "owner_id")
        recipient = _required_text(
            recipient_user_id,
            "recipient_user_id",
        )
        state = self._read_state()
        report = next(
            (
                item
                for item in state["reports"]
                if item.get("id") == identifier
                and item.get("ownerId") == owner
                and not item.get("deletedAt")
            ),
            None,
        )
        if report is None:
            return False
        before = len(state["shares"])
        state["shares"] = [
            item
            for item in state["shares"]
            if not (
                item.get("reportId") == identifier
                and item.get("recipientUserId") == recipient
            )
        ]
        if len(state["shares"]) == before:
            return False
        self._write_state(state)
        return True

    def list_report_center(
        self,
        *,
        user_id: str,
        limit: int = 50,
    ) -> dict[str, list[dict[str, Any]]]:
        user = _required_text(user_id, "user_id")
        state = self._read_state()
        reports = {
            str(item["id"]): report_from_payload(item)
            for item in state["reports"]
            if not item.get("deletedAt")
        }
        mine = sorted(
            (
                report
                for report in reports.values()
                if report.ownerId == user and not report.isExample
            ),
            key=lambda report: report.updatedAt,
            reverse=True,
        )[:limit]
        example_candidates = sorted(
            (
                report
                for report in reports.values()
                if report.isExample
            ),
            key=lambda report: report.updatedAt,
            reverse=True,
        )
        example_titles: set[str] = set()
        examples: list[ReportRecord] = []
        for report in example_candidates:
            if report.title in example_titles:
                continue
            example_titles.add(report.title)
            examples.append(report)
            if len(examples) >= limit:
                break
        shared: list[dict[str, Any]] = []
        for item in state["shares"]:
            if item.get("recipientUserId") != user:
                continue
            report = reports.get(str(item.get("reportId") or ""))
            if report is None or report.isExample:
                continue
            share = share_from_payload(item)
            shared.append(
                {
                    **share_to_payload(share),
                    "report": report_to_payload(report),
                }
            )
        shared.sort(
            key=lambda item: item["report"]["updatedAt"],
            reverse=True,
        )
        return {
            "mine": [
                {"report": report_to_payload(report)}
                for report in mine
            ],
            "sharedWithMe": shared[:limit],
            "examples": [
                {"report": report_to_payload(report)}
                for report in examples
            ],
        }

    def _read_state(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"reports": [], "shares": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid_report_store")
        reports = payload.get("reports")
        shares = payload.get("shares")
        if not isinstance(reports, list) or not isinstance(shares, list):
            raise ValueError("invalid_report_store")
        return {"reports": reports, "shares": shares}

    def _write_state(
        self,
        state: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )


def _required_text(value: str | None, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required.")
    return text


def _optional_text(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _now() -> str:
    return datetime.now(UTC).isoformat()
