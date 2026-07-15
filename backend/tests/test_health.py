import os

import httpx
import pytest
from pydantic import ValidationError

os.environ.setdefault("APP_ENV", "test")

from app.config import Settings
from app.main import create_app


@pytest.mark.anyio
async def test_health_returns_ok_status() -> None:
    transport = httpx.ASGITransport(app=create_app(Settings(app_env="test")))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_required_configuration_has_clear_non_sensitive_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    assert "app_env" in str(error.value)
    assert "OPENAI_API_KEY" not in str(error.value)
