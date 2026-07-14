import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("APP_ENV", "test")

from app.config import Settings


def test_database_url_is_required_without_echoing_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings(app_env="test", _env_file=None)

    assert "database_url" in str(error.value)
    assert "readonly-password" not in str(error.value)
