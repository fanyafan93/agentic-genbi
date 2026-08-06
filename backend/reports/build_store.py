from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.reports.build_models import (
    ReportBuildRecord,
    report_build_from_payload,
    report_build_to_payload,
)
from backend.reports.models import ReportRecord
from backend.reports.schema import report_config_payload
from backend.reports.store import ReportStore


DEFAULT_REPORT_BUILD_STORE_PATH = Path(
    ".resource-index/report-builds.json"
)
ACTIVE_BUILD_STATUSES = {"building", "validating", "failed"}


class ReportBuildStore:
    """Lock-protected JSON fallback for persisted Report builds."""

    def __init__(
        self,
        path: Path = DEFAULT_REPORT_BUILD_STORE_PATH,
        *,
        report_store: ReportStore | None = None,
    ) -> None:
        self.path = path
        self.report_store = report_store or ReportStore()
        self._lock = RLock()

    def create_build(
        self,
        record: ReportBuildRecord,
    ) -> ReportBuildRecord:
        with self._lock:
            state = self._read_state()
            if any(item.get("id") == record.id for item in state["builds"]):
                raise ValueError("report_build_already_exists")
            state["builds"].append(report_build_to_payload(record))
            self._write_state(state)
            return report_build_from_payload(
                report_build_to_payload(record)
            )

    def get_build(self, build_id: str) -> ReportBuildRecord | None:
        identifier = _required_text(build_id, "build_id")
        with self._lock:
            item = next(
                (
                    value
                    for value in self._read_state()["builds"]
                    if value.get("id") == identifier
                ),
                None,
            )
            return report_build_from_payload(item) if item else None

    def get_active_for_session(
        self,
        session_id: str,
        *,
        owner_id: str | None = None,
    ) -> ReportBuildRecord | None:
        session = _required_text(session_id, "session_id")
        owner = str(owner_id or "").strip() or None
        now = datetime.now(UTC)
        with self._lock:
            candidates = [
                report_build_from_payload(item)
                for item in self._read_state()["builds"]
                if item.get("sessionId") == session
                and item.get("status") in ACTIVE_BUILD_STATUSES
                and (owner is None or item.get("ownerId") == owner)
                and _parse_datetime(str(item.get("expiresAt"))) > now
            ]
        candidates.sort(
            key=lambda record: (record.updatedAt, record.revision),
            reverse=True,
        )
        return candidates[0] if candidates else None

    def mutate_build(
        self,
        build_id: str,
        *,
        owner_id: str,
        mutation: Callable[
            [ReportBuildRecord],
            ReportBuildRecord,
        ],
    ) -> ReportBuildRecord | None:
        identifier = _required_text(build_id, "build_id")
        owner = _required_text(owner_id, "owner_id")
        with self._lock:
            state = self._read_state()
            index = next(
                (
                    index
                    for index, item in enumerate(state["builds"])
                    if item.get("id") == identifier
                    and item.get("ownerId") == owner
                ),
                None,
            )
            if index is None:
                return None
            current = report_build_from_payload(state["builds"][index])
            updated = mutation(current)
            if updated.id != current.id or updated.ownerId != current.ownerId:
                raise ValueError("report_build_identity_changed")
            state["builds"][index] = report_build_to_payload(updated)
            self._write_state(state)
            return report_build_from_payload(
                report_build_to_payload(updated)
            )

    def publish_build(
        self,
        build_id: str,
        *,
        owner_id: str,
        turn_id: str,
    ) -> tuple[ReportBuildRecord, ReportRecord] | None:
        identifier = _required_text(build_id, "build_id")
        owner = _required_text(owner_id, "owner_id")
        turn = _required_text(turn_id, "turn_id")
        with self._lock:
            state = self._read_state()
            index = next(
                (
                    index
                    for index, item in enumerate(state["builds"])
                    if item.get("id") == identifier
                    and item.get("ownerId") == owner
                ),
                None,
            )
            if index is None:
                return None
            current = report_build_from_payload(state["builds"][index])
            if current.publishedReportId:
                report = self.report_store.get_report(
                    current.publishedReportId
                )
                if report is None:
                    raise ValueError("published_report_not_found")
                return current, report

            normalized = report_config_payload(current.content)
            report = self.report_store.create_report(
                normalized,
                owner_id=owner,
                turn_id=turn,
                report_id=f"report_{uuid4().hex}",
            )
            now = datetime.now(UTC)
            published = replace(
                current,
                status="published",
                content=normalized,
                validationErrors=[],
                revision=current.revision + 1,
                publishedReportId=report.id,
                lastSuccessfulStep="publish_report_build",
                updatedAt=now.isoformat(),
                expiresAt=(now + timedelta(hours=24)).isoformat(),
            )
            state["builds"][index] = report_build_to_payload(published)
            self._write_state(state)
            return published, report

    def cleanup_expired(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(UTC)
        with self._lock:
            state = self._read_state()
            retained = [
                item
                for item in state["builds"]
                if _parse_datetime(str(item.get("expiresAt")))
                > current_time
            ]
            removed = len(state["builds"]) - len(retained)
            if removed:
                state["builds"] = retained
                self._write_state(state)
            return removed

    def _read_state(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"builds": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("builds"), list)
        ):
            raise ValueError("invalid_report_build_store")
        return {"builds": payload["builds"]}

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


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_report_build_timestamp") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
