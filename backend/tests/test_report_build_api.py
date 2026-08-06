from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.analysis_api import create_app
from backend.harness.codex_projection_store import CodexProjectionStore
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.session_catalog import SessionCatalog
from backend.reports.build_context import ReportToolExecutionRegistry
from backend.reports.build_service import (
    ReportBuildContext,
    ReportBuildService,
)
from backend.reports.build_store import ReportBuildStore
from backend.reports.query_service import ReportQueryService
from backend.reports.store import ReportStore


class _QueryRunner:
    def run(
        self,
        data_source: str,
        sql: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        return [{"channel": "抖音", "sales": 10}]


def _client(
    tmp_path: Path,
) -> tuple[
    TestClient,
    ReportToolExecutionRegistry,
    ReportBuildStore,
    SessionCatalog,
]:
    reports = ReportStore(tmp_path / "reports.json")
    builds = ReportBuildStore(
        tmp_path / "report-builds.json",
        report_store=reports,
    )
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    catalog = SessionCatalog(tmp_path / "sessions.jsonl")
    app = create_app(
        analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
        report_store=reports,
        report_build_store=builds,
        report_tool_execution_registry=registry,
        report_query_service=ReportQueryService(_QueryRunner()),
        session_catalog=catalog,
        codex_projection_store=CodexProjectionStore(
            tmp_path / "turns.jsonl"
        ),
    )
    return TestClient(app), registry, builds, catalog


def _bound_token(
    registry: ReportToolExecutionRegistry,
) -> str:
    token = registry.reserve(
        owner_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        roles=("analyst",),
    )
    registry.bind(
        token,
        session_id="session-1",
        turn_id="turn-1",
    )
    return token


def _principal_headers(
    *,
    user_id: str = "user-1",
) -> dict[str, str]:
    return {
        "X-GenBI-Tenant-Id": "tenant-1",
        "X-GenBI-User-Id": user_id,
        "X-GenBI-Workspace-Id": "workspace-1",
    }


def _seed_active_build(
    builds: ReportBuildStore,
    catalog: SessionCatalog,
) -> str:
    catalog.register_session(
        "session-1",
        product_kind="analysis_task",
        title="渠道销售",
        user_id="user-1",
        metadata={
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
        },
    )
    service = ReportBuildService(builds)
    context = ReportBuildContext(
        owner_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
    )
    started = service.invoke(
        "start_report_build",
        {"title": "渠道销售", "subtitle": "2026-08"},
        context,
    )
    updated = service.invoke(
        "upsert_report_query",
        {
            "build_id": started["buildId"],
            "query_id": "q-sales",
            "query": {
                "dataSource": "mysql",
                "sql": "SELECT channel, sales FROM sales",
                "parameters": {},
                "pagination": False,
            },
        },
        context,
    )
    assert updated["ok"] is True
    return str(started["buildId"])


def test_turn_binding_detects_existing_active_report_build(
    tmp_path: Path,
) -> None:
    _, registry, builds, catalog = _client(tmp_path)
    _seed_active_build(builds, catalog)
    token = registry.reserve(owner_id="user-1")
    execution_id = registry.execution_id(token)

    registry.bind(
        token,
        session_id="session-1",
        turn_id="turn-2",
    )

    assert registry.has_incomplete_report_build(execution_id) is True


def test_internal_report_tool_requires_execution_token(
    tmp_path: Path,
) -> None:
    client, _, _, _ = _client(tmp_path)

    response = client.post(
        "/api/internal/report-build-tools/start_report_build",
        json={"title": "渠道销售", "subtitle": "2026-08"},
    )

    assert response.status_code == 401


def test_internal_report_tool_rejects_model_supplied_context(
    tmp_path: Path,
) -> None:
    client, registry, _, _ = _client(tmp_path)
    token = _bound_token(registry)

    response = client.post(
        "/api/internal/report-build-tools/start_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "渠道销售",
            "subtitle": "2026-08",
            "owner_id": "attacker",
            "session_id": "other-session",
            "turn_id": "other-turn",
        },
    )

    assert response.status_code == 422


def test_internal_report_tool_uses_only_signed_context(
    tmp_path: Path,
) -> None:
    client, registry, builds, _ = _client(tmp_path)
    token = _bound_token(registry)

    response = client.post(
        "/api/internal/report-build-tools/start_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "渠道销售", "subtitle": "2026-08"},
    )

    assert response.status_code == 200
    payload = response.json()
    saved = builds.get_build(payload["buildId"])
    assert saved is not None
    assert saved.ownerId == "user-1"
    assert saved.sessionId == "session-1"
    assert saved.turnId == "turn-1"


def test_scoped_minimax_adapter_blocks_fourth_no_progress_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, registry, _, _ = _client(tmp_path)
    token = _bound_token(registry)
    execution_id = registry.execution_id(token)
    start = client.post(
        "/api/internal/report-build-tools/start_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "渠道销售", "subtitle": "2026-08"},
    )
    assert start.status_code == 200
    monkeypatch.setattr(
        "backend.api.analysis_api.proxy_minimax_response",
        lambda raw_body, *, stream: (
            200,
            {"content-type": "application/json"},
            b'{"id":"response-1"}',
        ),
    )

    for _ in range(3):
        response = client.post(
            (
                "/api/codex-minimax/v1/executions/"
                f"{execution_id}/responses"
            ),
            json={"model": "MiniMax-M3", "stream": False},
        )
        assert response.status_code == 200

    blocked = client.post(
        (
            "/api/codex-minimax/v1/executions/"
            f"{execution_id}/responses"
        ),
        json={"model": "MiniMax-M3", "stream": False},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == (
        "report_build_no_progress"
    )


def test_persisted_failed_step_resets_no_progress_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, registry, _, _ = _client(tmp_path)
    token = _bound_token(registry)
    execution_id = registry.execution_id(token)
    start = client.post(
        "/api/internal/report-build-tools/start_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "渠道销售", "subtitle": "2026-08"},
    )
    assert start.status_code == 200
    monkeypatch.setattr(
        "backend.api.analysis_api.proxy_minimax_response",
        lambda raw_body, *, stream: (
            200,
            {"content-type": "application/json"},
            b'{"id":"response-1"}',
        ),
    )

    for _ in range(2):
        response = client.post(
            (
                "/api/codex-minimax/v1/executions/"
                f"{execution_id}/responses"
            ),
            json={"model": "MiniMax-M3", "stream": False},
        )
        assert response.status_code == 200

    failed_step = client.post(
        "/api/internal/report-build-tools/upsert_report_query",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "build_id": start.json()["buildId"],
            "query_id": "q-sales",
            "query": {
                "dataSource": "doris",
                "sql": (
                    "SELECT SUM(nsales_amt) FROM "
                    "dm.dm_channel_mtsg_sale_total "
                    "WHERE vdate >= ${start_date}"
                ),
                "parameters": [],
                "pagination": False,
            },
        },
    )
    assert failed_step.status_code == 200
    assert failed_step.json()["ok"] is False
    assert failed_step.json()["revision"] == 1

    for _ in range(3):
        response = client.post(
            (
                "/api/codex-minimax/v1/executions/"
                f"{execution_id}/responses"
            ),
            json={"model": "MiniMax-M3", "stream": False},
        )
        assert response.status_code == 200

    blocked = client.post(
        (
            "/api/codex-minimax/v1/executions/"
            f"{execution_id}/responses"
        ),
        json={"model": "MiniMax-M3", "stream": False},
    )
    assert blocked.status_code == 409


def test_malformed_mutation_arguments_persist_failure_and_allow_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, registry, builds, _ = _client(tmp_path)
    token = _bound_token(registry)
    execution_id = registry.execution_id(token)
    start = client.post(
        "/api/internal/report-build-tools/start_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "渠道销售", "subtitle": "2026-08"},
    )
    assert start.status_code == 200
    monkeypatch.setattr(
        "backend.api.analysis_api.proxy_minimax_response",
        lambda raw_body, *, stream: (
            200,
            {"content-type": "application/json"},
            b'{"id":"response-1"}',
        ),
    )

    for _ in range(2):
        response = client.post(
            (
                "/api/codex-minimax/v1/executions/"
                f"{execution_id}/responses"
            ),
            json={"model": "MiniMax-M3", "stream": False},
        )
        assert response.status_code == 200

    malformed = client.post(
        "/api/internal/report-build-tools/upsert_report_query",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "build_id": start.json()["buildId"],
            "query_id": "q-sales",
            "query": "",
            "sql": "SELECT 1",
        },
    )

    assert malformed.status_code == 200
    payload = malformed.json()
    assert payload["ok"] is False
    assert payload["revision"] == 1
    assert payload["retryable"] is True
    saved = builds.get_build(start.json()["buildId"])
    assert saved is not None
    assert saved.status == "failed"
    assert saved.stepAttempts == {
        "upsert_report_query:q-sales": 1,
    }

    for _ in range(2):
        response = client.post(
            (
                "/api/codex-minimax/v1/executions/"
                f"{execution_id}/responses"
            ),
            json={"model": "MiniMax-M3", "stream": False},
        )
        assert response.status_code == 200

    read_failed_build = client.post(
        "/api/internal/report-build-tools/get_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={"build_id": start.json()["buildId"]},
    )
    assert read_failed_build.status_code == 200

    for _ in range(3):
        response = client.post(
            (
                "/api/codex-minimax/v1/executions/"
                f"{execution_id}/responses"
            ),
            json={"model": "MiniMax-M3", "stream": False},
        )
        assert response.status_code == 200

    blocked = client.post(
        (
            "/api/codex-minimax/v1/executions/"
            f"{execution_id}/responses"
        ),
        json={"model": "MiniMax-M3", "stream": False},
    )
    assert blocked.status_code == 409


def test_third_malformed_mutation_failure_exhausts_correction_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, registry, _, _ = _client(tmp_path)
    token = _bound_token(registry)
    execution_id = registry.execution_id(token)
    start = client.post(
        "/api/internal/report-build-tools/start_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "渠道销售", "subtitle": "2026-08"},
    )
    assert start.status_code == 200
    monkeypatch.setattr(
        "backend.api.analysis_api.proxy_minimax_response",
        lambda raw_body, *, stream: (
            200,
            {"content-type": "application/json"},
            b'{"id":"response-1"}',
        ),
    )
    malformed_body = {
        "build_id": start.json()["buildId"],
        "query_id": "q-sales",
        "query": "",
        "sql": "SELECT 1",
    }

    failures = [
        client.post(
            "/api/internal/report-build-tools/upsert_report_query",
            headers={"Authorization": f"Bearer {token}"},
            json=malformed_body,
        ).json()
        for _ in range(3)
    ]

    assert [failure["retryable"] for failure in failures] == [
        True,
        True,
        False,
    ]
    blocked = client.post(
        (
            "/api/codex-minimax/v1/executions/"
            f"{execution_id}/responses"
        ),
        json={"model": "MiniMax-M3", "stream": False},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == (
        "report_build_no_progress"
    )


def test_active_build_route_recovers_renderable_content(
    tmp_path: Path,
) -> None:
    client, _, builds, catalog = _client(tmp_path)
    build_id = _seed_active_build(builds, catalog)

    response = client.get(
        "/api/analysis/sessions/session-1/report-builds/active",
        headers=_principal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["build"]["id"] == build_id
    assert payload["build"]["revision"] == 1
    assert payload["report"]["buildId"] == build_id
    assert payload["report"]["queries"]["q-sales"]["sql"].startswith(
        "SELECT"
    )


def test_exact_build_route_hides_other_users_build(
    tmp_path: Path,
) -> None:
    client, _, builds, catalog = _client(tmp_path)
    build_id = _seed_active_build(builds, catalog)

    response = client.get(
        f"/api/report-builds/{build_id}",
        headers=_principal_headers(user_id="other-user"),
    )

    assert response.status_code == 404


def test_build_query_uses_same_readonly_query_service(
    tmp_path: Path,
) -> None:
    client, _, builds, catalog = _client(tmp_path)
    build_id = _seed_active_build(builds, catalog)

    response = client.post(
        f"/api/report-builds/{build_id}/queries/q-sales",
        headers=_principal_headers(),
        json={"filters": {}, "page": 1, "pageSize": 50},
    )

    assert response.status_code == 200
    assert response.json()["rows"] == [
        {"channel": "抖音", "sales": 10}
    ]
