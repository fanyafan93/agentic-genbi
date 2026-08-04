"""Verify that ``POST /api/analysis/tasks`` is the only place a
frontend can land on a real task id — the endpoint must NOT accept
or echo a client-side draft_* placeholder, and the response must
carry a backend-issued ``thread.id`` that the client can trust."""

from __future__ import annotations

from backend.analysis.asset_store import AnalysisAssetStore
from backend.tests.auth_test_client import auth_client, build_test_app


def _build_app():
    # Production code paths now require Postgres at boot; this test
    # suite injects in-memory stores explicitly. The previous
    # "GENBI_PERSISTENCE unset -> in-memory store" silent fallback
    # is exactly the data-loss pattern the contract prohibits.
    return build_test_app(
        knowledge_store="auto",
        analysis_asset_store=AnalysisAssetStore(),
        interactive_report_store="auto",
        thread_store="auto",
    )


def test_post_tasks_creates_backend_issued_thread_id():
    """``POST /api/analysis/tasks`` returns a server-issued taskId;
    the response shape explicitly wraps it in ``task`` so the frontend
    has a single, addressable contract. There is no draft_*
    placeholder on the wire."""
    app = _build_app()
    with auth_client(app) as client:
        response = client.post(
            "/api/analysis/tasks",
            json={"title": "新建分析任务"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "task" in body, "response shape must use a single ``task`` envelope"
        task = body["task"]
        thread_id = task["id"]
        assert thread_id.startswith("analysis_thread_"), (
            "taskId must be backend-issued; no draft_* placeholder is allowed"
        )
        assert "draft_" not in thread_id
        assert task["status"] == "waiting_for_question"
        assert task["title"] == "新建分析任务"


def test_post_tasks_rejects_draft_placeholder_in_title():
    """If the client tries to send a draft_* string as the title, the
    endpoint should still create a real task. The point is to verify
    the contract: a draft_ title never becomes a draft_ id."""
    app = _build_app()
    with auth_client(app) as client:
        response = client.post(
            "/api/analysis/tasks",
            json={"title": "draft_should_not_leak"},
        )
        assert response.status_code == 200
        body = response.json()
        task = body["task"]
        # Title is preserved verbatim but the canonical id is still
        # backend-issued; the prefix is a deliberate discriminator.
        assert task["title"] == "draft_should_not_leak"
        assert not task["id"].startswith("draft_")
        assert task["id"].startswith("analysis_thread_")
