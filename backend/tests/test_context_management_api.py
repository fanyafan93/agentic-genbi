from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.analysis_api import create_app
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime


def test_system_context_skills_is_protected_and_returns_metadata_only() -> None:
    with (
        patch.dict(
            "os.environ",
            {"GENBI_SYSTEM_API_TOKEN": "internal-system-token"},
            clear=False,
        ),
        patch(
            "backend.api.analysis_api.list_installed_skills",
            return_value=[
                {
                    "name": "openai-docs",
                    "description": "Read official documentation.",
                    "scope": "system",
                }
            ],
        ),
    ):
        client = TestClient(
            create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
        )

        denied = client.get("/api/system/context/skills")
        allowed = client.get(
            "/api/system/context/skills",
            headers={"X-GenBI-System-Token": "internal-system-token"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json() == {
        "skills": [
            {
                "name": "openai-docs",
                "description": "Read official documentation.",
                "scope": "system",
            }
        ]
    }
    assert "content" not in allowed.text
    assert "path" not in allowed.text
