from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.reports.build_models import ReportBuildRecord
from backend.reports.build_store import ReportBuildStore
from backend.reports.store import ReportStore


def _record(
    *,
    identifier: str = "build-1",
    owner_id: str = "user-1",
    session_id: str = "session-1",
    revision: int = 0,
    expires_at: str | None = None,
) -> ReportBuildRecord:
    now = datetime.now(UTC)
    return ReportBuildRecord(
        id=identifier,
        ownerId=owner_id,
        sessionId=session_id,
        turnId="turn-1",
        targetReportId=None,
        status="building",
        content={
            "title": "渠道销售",
            "subtitle": "2026-08",
            "layout": {"content": [], "zones": {}},
            "filters": {},
            "queries": {},
            "charts": {},
            "tables": {},
        },
        validationErrors=[],
        revision=revision,
        publishedReportId=None,
        lastSuccessfulStep=None,
        stepAttempts={},
        createdAt=now.isoformat(),
        updatedAt=now.isoformat(),
        expiresAt=expires_at or (now + timedelta(days=7)).isoformat(),
    )


def test_json_store_restores_active_build_and_persists_one_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report-builds.json"
    store = ReportBuildStore(path, report_store=ReportStore(tmp_path / "reports.json"))
    store.create_build(_record())

    updated = store.mutate_build(
        "build-1",
        owner_id="user-1",
        mutation=lambda current: replace(
            current,
            revision=current.revision + 1,
            content={**current.content, "charts": {"chart-1": {}}},
        ),
    )
    restored = ReportBuildStore(
        path,
        report_store=ReportStore(tmp_path / "reports.json"),
    ).get_active_for_session("session-1", owner_id="user-1")

    assert updated is not None
    assert updated.revision == 1
    assert restored is not None
    assert restored.content["charts"] == {"chart-1": {}}


def test_json_store_does_not_mutate_a_build_owned_by_someone_else(
    tmp_path: Path,
) -> None:
    store = ReportBuildStore(
        tmp_path / "report-builds.json",
        report_store=ReportStore(tmp_path / "reports.json"),
    )
    store.create_build(_record())

    updated = store.mutate_build(
        "build-1",
        owner_id="user-2",
        mutation=lambda current: replace(current, revision=99),
    )

    assert updated is None
    assert store.get_build("build-1").revision == 0


def test_json_store_cleans_only_expired_unpublished_builds(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    store = ReportBuildStore(
        tmp_path / "report-builds.json",
        report_store=ReportStore(tmp_path / "reports.json"),
    )
    store.create_build(
        _record(
            identifier="expired",
            expires_at=(now - timedelta(seconds=1)).isoformat(),
        )
    )
    store.create_build(
        _record(
            identifier="current",
            expires_at=(now + timedelta(days=1)).isoformat(),
        )
    )

    removed = store.cleanup_expired(now=now)

    assert removed == 1
    assert store.get_build("expired") is None
    assert store.get_build("current") is not None
