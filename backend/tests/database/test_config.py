import os
from pathlib import Path

import pytest
from pydantic import ValidationError

os.environ.setdefault("APP_ENV", "test")

from app.config import Settings


def test_default_env_file_is_resolved_from_the_repository_root() -> None:
    from app.config import PROJECT_ENV_FILE

    assert PROJECT_ENV_FILE.name == ".env"
    assert PROJECT_ENV_FILE.parent == Path(__file__).resolve().parents[3]
    assert Path(Settings.model_config["env_file"]) == PROJECT_ENV_FILE


def test_database_url_is_required_without_echoing_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings(app_env="test", _env_file=None)

    assert "database_url" in str(error.value)
    assert "readonly-password" not in str(error.value)
