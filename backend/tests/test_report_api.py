from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.analysis_api import create_app
from backend.harness.codex_projection_store import CodexProjectionStore
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.session_catalog import SessionCatalog
from backend.reports.query_service import ReportQueryService
from backend.reports.store import ReportStore
from backend.tests.test_report_store import report_config


class FakeQueryRunner:
    def run(
        self,
        _data_source: str,
        sql: str,
        _params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if "genbi_count" in sql:
            return [{"total": 1}]
        return [{"region": "华东", "amount": 1200}]


def _client(tmp_path: Path) -> tuple[
    TestClient,
    ReportStore,
    CodexProjectionStore,
]:
    report_store = ReportStore(tmp_path / "reports.json")
    projection_store = CodexProjectionStore(
        path=tmp_path / "codex-projections.jsonl"
    )
    app = create_app(
        analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
        report_store=report_store,
        report_query_service=ReportQueryService(FakeQueryRunner()),
        session_catalog=SessionCatalog(
            path=tmp_path / "session-catalog.jsonl"
        ),
        codex_projection_store=projection_store,
    )
    return TestClient(app), report_store, projection_store


def test_report_crud_uses_direct_paths_and_full_put(
    tmp_path: Path,
) -> None:
    client, _, _ = _client(tmp_path)

    created = client.post(
        "/api/reports",
        json={"ownerId": "user-1", **report_config()},
    )
    report_id = created.json()["report"]["id"]
    updated = client.put(
        f"/api/reports/{report_id}",
        json={"ownerId": "user-1", **report_config("修订")},
    )
    listed = client.get(
        "/api/reports",
        params={"owner_id": "user-1"},
    )
    opened = client.get(f"/api/reports/{report_id}")
    legacy = client.get("/api/analysis/reports")

    assert created.status_code == 201
    assert created.json()["report"]["turnId"] is None
    assert updated.status_code == 200
    assert updated.json()["report"]["title"] == "修订"
    assert listed.json()["reports"][0]["id"] == report_id
    assert opened.json()["report"]["id"] == report_id
    assert legacy.status_code == 404


def test_report_response_derives_source_session_from_turn(
    tmp_path: Path,
) -> None:
    client, report_store, projection_store = _client(tmp_path)
    projection_store.save_turn(
        session_id="session-1",
        turn_id="turn-1",
        input_kind="start",
        input_text="生成报表",
        status="completed",
    )
    report = report_store.create_report(
        report_config(),
        owner_id="user-1",
        turn_id="turn-1",
    )

    opened = client.get(f"/api/reports/{report.id}")
    by_session = client.get(
        "/api/reports",
        params={"session_id": "session-1"},
    )

    assert opened.json()["report"]["sourceSessionId"] == "session-1"
    assert by_session.json()["reports"][0]["id"] == report.id


def test_report_query_endpoint_loads_saved_sql_and_rejects_client_sql(
    tmp_path: Path,
) -> None:
    client, report_store, _ = _client(tmp_path)
    report = report_store.create_report(
        report_config(),
        owner_id="user-1",
    )

    rejected = client.post(
        f"/api/reports/{report.id}/queries/sales-query",
        json={
            "filters": {"region": "华东"},
            "page": 1,
            "pageSize": 50,
            "sql": "DELETE FROM sales",
        },
    )
    executed = client.post(
        f"/api/reports/{report.id}/queries/sales-query",
        json={
            "filters": {"region": "华东"},
            "page": 1,
            "pageSize": 50,
        },
    )

    assert rejected.status_code == 422
    assert executed.status_code == 200
    assert executed.json()["rows"] == [
        {"region": "华东", "amount": 1200}
    ]
    assert executed.json()["total"] == 1


def test_report_sharing_and_delete_use_direct_paths(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    created = client.post(
        "/api/reports",
        json={"ownerId": "owner-1", **report_config()},
    )
    report_id = created.json()["report"]["id"]

    shared = client.post(
        f"/api/reports/{report_id}/shares",
        json={
            "ownerId": "owner-1",
            "recipientUserId": "user-2",
            "permission": "view_and_reuse",
        },
    )
    center = client.get(
        "/api/report-center",
        params={"user_id": "user-2"},
    )
    deleted = client.delete(
        f"/api/reports/{report_id}",
        params={"owner_id": "owner-1"},
    )
    center_after_delete = client.get(
        "/api/report-center",
        params={"user_id": "user-2"},
    )

    assert shared.status_code == 200
    assert center.json()["sharedWithMe"][0]["report"]["id"] == report_id
    assert deleted.status_code == 200
    assert center_after_delete.json()["sharedWithMe"] == []


def test_invalid_report_and_missing_query_use_contract_status_codes(
    tmp_path: Path,
) -> None:
    client, report_store, _ = _client(tmp_path)
    invalid = report_config()
    invalid["queries"]["sales-query"]["sql"] = "DELETE FROM sales"
    invalid_response = client.post(
        "/api/reports",
        json={"ownerId": "user-1", **invalid},
    )
    report = report_store.create_report(
        report_config(),
        owner_id="user-1",
    )
    missing_query = client.post(
        f"/api/reports/{report.id}/queries/missing",
        json={"filters": {"region": "华东"}},
    )

    assert invalid_response.status_code == 422
    assert missing_query.status_code == 404

