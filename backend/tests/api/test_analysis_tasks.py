import os
from uuid import uuid4

import httpx
import pytest

os.environ.setdefault("APP_ENV", "test")

from app.config import Settings
from app.main import create_app
from app.services.task_service import TaskService


@pytest.mark.anyio
async def test_create_task_returns_queued_then_get_returns_fixed_completed_report() -> None:
    app = create_app(Settings(app_env="test"), task_service=TaskService())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/analysis-tasks", json={"question": "查看固定报告"}
        )
        task_id = created.json()["task_id"]
        fetched = await client.get(f"/api/v1/analysis-tasks/{task_id}")

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert created.json()["report"] is None
    assert created.json()["completed_at"] is None
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "succeeded"
    assert fetched.json()["report"]["title"] == "固定销售概览"
    assert fetched.json()["completed_at"] is not None


@pytest.mark.anyio
async def test_default_application_reports_missing_minimax_configuration() -> None:
    settings = Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@127.0.0.1:3307/analytics",
        _env_file=None,
    )
    transport = httpx.ASGITransport(app=create_app(settings))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/v1/analysis-tasks", json={"question": "查看销售额"})
        fetched = await client.get(f"/api/v1/analysis-tasks/{created.json()['task_id']}")

    assert fetched.json()["status"] == "failed"
    assert fetched.json()["report"] is None
    assert fetched.json()["error"] == {
        "code": "PROVIDER_NOT_CONFIGURED",
        "message": "Analysis provider is not configured.",
        "retryable": False,
        "details": None,
    }


@pytest.mark.anyio
async def test_blank_and_overlong_questions_return_validation_error_envelope() -> None:
    app = create_app(Settings(app_env="test"), task_service=TaskService())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        blank = await client.post("/api/v1/analysis-tasks", json={"question": "   "})
        overlong = await client.post("/api/v1/analysis-tasks", json={"question": "a" * 4001})

    for response in (blank, overlong):
        assert response.status_code == 422
        assert response.json() == {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数无效。",
                "retryable": False,
                "details": None,
            }
        }


@pytest.mark.anyio
async def test_unknown_task_returns_task_not_found_error_envelope() -> None:
    app = create_app(Settings(app_env="test"), task_service=TaskService())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/analysis-tasks/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "TASK_NOT_FOUND",
            "message": "分析任务不存在或状态已因服务重启而丢失。",
            "retryable": False,
            "details": None,
        }
    }
