from __future__ import annotations

import os
import re
import uuid
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlparse

from backend.system_management.mcp_registry import McpSecretCipher
from backend.persistence.postgres_stores import get_postgres_database_url


LOGGER = logging.getLogger(__name__)
VALID_CONNECTION_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
SUPPORTED_PROVIDER_TYPES = frozenset(
    {"openai", "minimax", "openai_compatible"}
)


class ModelConnectionError(ValueError):
    pass


class ModelConnectionConflict(ModelConnectionError):
    pass


class ModelConnectionNotFound(ModelConnectionError):
    pass


@dataclass
class ModelConnectionRecord:
    id: str
    name: str
    display_name: str
    provider_type: str
    model: str
    base_url: str
    encrypted_api_key: str
    enabled: bool
    is_default: bool
    created_by_id: str
    updated_by_id: str
    created_at: datetime
    updated_at: datetime
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None


@dataclass(frozen=True)
class ModelRuntimeConnection:
    name: str
    display_name: str
    provider_type: str
    model: str
    base_url: str
    api_key: str
    source: str = "managed"

    @property
    def provider_id(self) -> str:
        normalized = re.sub(r"[^a-z0-9_]", "_", self.name.lower())
        return f"genbi_{normalized}"


class ModelConnectionRepository(Protocol):
    def list(self) -> list[ModelConnectionRecord]: ...

    def get(self, name: str) -> ModelConnectionRecord | None: ...

    def create(self, record: ModelConnectionRecord) -> ModelConnectionRecord: ...

    def update(self, record: ModelConnectionRecord) -> ModelConnectionRecord: ...

    def delete(self, name: str) -> None: ...

    def set_default(
        self,
        name: str,
        *,
        actor_id: str,
        updated_at: datetime,
    ) -> ModelConnectionRecord: ...


class MemoryModelConnectionRepository:
    def __init__(self) -> None:
        self.records: dict[str, ModelConnectionRecord] = {}

    def list(self) -> list[ModelConnectionRecord]:
        return [deepcopy(record) for record in self.records.values()]

    def get(self, name: str) -> ModelConnectionRecord | None:
        record = self.records.get(name)
        return deepcopy(record) if record else None

    def create(self, record: ModelConnectionRecord) -> ModelConnectionRecord:
        if record.name in self.records:
            raise ModelConnectionConflict(
                f"Model connection `{record.name}` already exists."
            )
        self.records[record.name] = deepcopy(record)
        return deepcopy(record)

    def update(self, record: ModelConnectionRecord) -> ModelConnectionRecord:
        if record.name not in self.records:
            raise ModelConnectionNotFound(
                f"Model connection `{record.name}` was not found."
            )
        self.records[record.name] = deepcopy(record)
        return deepcopy(record)

    def delete(self, name: str) -> None:
        if name not in self.records:
            raise ModelConnectionNotFound(
                f"Model connection `{name}` was not found."
            )
        del self.records[name]

    def set_default(
        self,
        name: str,
        *,
        actor_id: str,
        updated_at: datetime,
    ) -> ModelConnectionRecord:
        if name not in self.records:
            raise ModelConnectionNotFound(
                f"Model connection `{name}` was not found."
            )
        for key, record in list(self.records.items()):
            self.records[key] = ModelConnectionRecord(
                **{
                    **record.__dict__,
                    "is_default": key == name,
                    "updated_by_id": actor_id if key == name else record.updated_by_id,
                    "updated_at": updated_at if key == name else record.updated_at,
                }
            )
        return deepcopy(self.records[name])


class PostgresModelConnectionRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def list(self) -> list[ModelConnectionRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM "ModelConnection"
                ORDER BY "isDefault" DESC, "displayName", name
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, name: str) -> ModelConnectionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM "ModelConnection"
                WHERE name = %s
                """,
                (name,),
            ).fetchone()
        return self._from_row(row) if row else None

    def create(
        self,
        record: ModelConnectionRecord,
    ) -> ModelConnectionRecord:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    INSERT INTO "ModelConnection" (
                        id, name, "displayName", "providerType", model,
                        "baseUrl", "encryptedApiKey", enabled, "isDefault",
                        "createdById", "updatedById", "createdAt", "updatedAt",
                        "lastTestedAt", "lastTestStatus", "lastTestMessage"
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    RETURNING *
                    """,
                    self._values(record),
                ).fetchone()
        except Exception as error:
            if getattr(error, "sqlstate", "") == "23505":
                raise ModelConnectionConflict(
                    f"Model connection `{record.name}` already exists."
                ) from error
            raise
        return self._from_row(row)

    def update(
        self,
        record: ModelConnectionRecord,
    ) -> ModelConnectionRecord:
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE "ModelConnection"
                SET
                    "displayName" = %s,
                    "providerType" = %s,
                    model = %s,
                    "baseUrl" = %s,
                    "encryptedApiKey" = %s,
                    enabled = %s,
                    "isDefault" = %s,
                    "updatedById" = %s,
                    "updatedAt" = %s,
                    "lastTestedAt" = %s,
                    "lastTestStatus" = %s,
                    "lastTestMessage" = %s
                WHERE name = %s
                RETURNING *
                """,
                (
                    record.display_name,
                    record.provider_type,
                    record.model,
                    record.base_url,
                    record.encrypted_api_key,
                    record.enabled,
                    record.is_default,
                    record.updated_by_id,
                    record.updated_at,
                    record.last_tested_at,
                    record.last_test_status,
                    record.last_test_message,
                    record.name,
                ),
            ).fetchone()
        if not row:
            raise ModelConnectionNotFound(
                f"Model connection `{record.name}` was not found."
            )
        return self._from_row(row)

    def delete(self, name: str) -> None:
        with self._connection() as connection:
            row = connection.execute(
                """
                DELETE FROM "ModelConnection"
                WHERE name = %s
                RETURNING name
                """,
                (name,),
            ).fetchone()
        if not row:
            raise ModelConnectionNotFound(
                f"Model connection `{name}` was not found."
            )

    def set_default(
        self,
        name: str,
        *,
        actor_id: str,
        updated_at: datetime,
    ) -> ModelConnectionRecord:
        with self._connection() as connection:
            target = connection.execute(
                """
                SELECT name, enabled
                FROM "ModelConnection"
                WHERE name = %s
                FOR UPDATE
                """,
                (name,),
            ).fetchone()
            if not target:
                raise ModelConnectionNotFound(
                    f"Model connection `{name}` was not found."
                )
            if not bool(target.get("enabled")):
                raise ModelConnectionConflict(
                    "Only an enabled model connection can be the default."
                )
            connection.execute(
                """
                UPDATE "ModelConnection"
                SET "isDefault" = false
                WHERE "isDefault" = true
                """
            )
            row = connection.execute(
                """
                UPDATE "ModelConnection"
                SET
                    "isDefault" = true,
                    "updatedById" = %s,
                    "updatedAt" = %s
                WHERE name = %s
                RETURNING *
                """,
                (actor_id, updated_at, name),
            ).fetchone()
        return self._from_row(row)

    def _connection(self) -> Any:
        from psycopg import connect
        from psycopg.rows import dict_row

        return connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _values(record: ModelConnectionRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.name,
            record.display_name,
            record.provider_type,
            record.model,
            record.base_url,
            record.encrypted_api_key,
            record.enabled,
            record.is_default,
            record.created_by_id,
            record.updated_by_id,
            record.created_at,
            record.updated_at,
            record.last_tested_at,
            record.last_test_status,
            record.last_test_message,
        )

    @staticmethod
    def _from_row(row: dict[str, Any]) -> ModelConnectionRecord:
        return ModelConnectionRecord(
            id=str(row["id"]),
            name=str(row["name"]),
            display_name=str(row["displayName"]),
            provider_type=str(row["providerType"]),
            model=str(row["model"]),
            base_url=str(row["baseUrl"]),
            encrypted_api_key=str(row["encryptedApiKey"]),
            enabled=bool(row["enabled"]),
            is_default=bool(row["isDefault"]),
            created_by_id=str(row["createdById"]),
            updated_by_id=str(row["updatedById"]),
            created_at=row["createdAt"],
            updated_at=row["updatedAt"],
            last_tested_at=row.get("lastTestedAt"),
            last_test_status=(
                str(row["lastTestStatus"])
                if row.get("lastTestStatus")
                else None
            ),
            last_test_message=(
                str(row["lastTestMessage"])
                if row.get("lastTestMessage")
                else None
            ),
        )


class ModelConnectionRegistry:
    def __init__(
        self,
        *,
        repository: ModelConnectionRepository,
        cipher: McpSecretCipher,
    ) -> None:
        self.repository = repository
        self.cipher = cipher

    def list(self) -> list[dict[str, Any]]:
        return [
            self._public_record(record)
            for record in sorted(
                self.repository.list(),
                key=lambda item: (
                    not item.is_default,
                    item.display_name.lower(),
                    item.name.lower(),
                ),
            )
        ]

    def get(self, name: str) -> dict[str, Any]:
        return self._public_record(self._require(name))

    def create(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        normalized = self._normalized_input(payload, creating=True)
        name = normalized["name"]
        if self.repository.get(name):
            raise ModelConnectionConflict(
                f"Model connection `{name}` already exists."
            )
        existing = self.repository.list()
        requested_default = bool(
            payload.get("isDefault") or payload.get("makeDefault")
        )
        is_default = requested_default or (not existing and normalized["enabled"])
        if is_default and not normalized["enabled"]:
            raise ModelConnectionConflict(
                "Only an enabled model connection can be the default."
            )
        now = datetime.now(timezone.utc)
        record = ModelConnectionRecord(
            id=uuid.uuid4().hex,
            name=name,
            display_name=normalized["displayName"],
            provider_type=normalized["providerType"],
            model=normalized["model"],
            base_url=normalized["baseUrl"],
            encrypted_api_key=self.cipher.encrypt(
                name,
                {"apiKey": normalized["apiKey"]},
            ),
            enabled=normalized["enabled"],
            is_default=is_default and not existing,
            created_by_id=actor_id,
            updated_by_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        created = self.repository.create(record)
        if is_default:
            created = self.repository.set_default(
                name,
                actor_id=actor_id,
                updated_at=now,
            )
        return self._public_record(created)

    def update(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self._require(name)
        if "name" in payload and str(payload["name"]).strip() != name:
            raise ModelConnectionConflict("Model connection name is immutable.")
        merged = {
            "name": existing.name,
            "displayName": existing.display_name,
            "providerType": existing.provider_type,
            "model": existing.model,
            "baseUrl": existing.base_url,
            "apiKey": "",
            "enabled": existing.enabled,
            **payload,
        }
        normalized = self._normalized_input(merged, creating=False)
        if existing.is_default and not normalized["enabled"]:
            raise ModelConnectionConflict(
                "Choose another default connection before disabling this one."
            )
        secrets = self.cipher.decrypt(
            name,
            existing.encrypted_api_key,
        )
        incoming_api_key = normalized["apiKey"]
        api_key = incoming_api_key or str(secrets.get("apiKey") or "")
        if not api_key:
            raise ModelConnectionError("apiKey is required.")
        updated = ModelConnectionRecord(
            **{
                **existing.__dict__,
                "display_name": normalized["displayName"],
                "provider_type": normalized["providerType"],
                "model": normalized["model"],
                "base_url": normalized["baseUrl"],
                "encrypted_api_key": self.cipher.encrypt(
                    name,
                    {"apiKey": api_key},
                ),
                "enabled": normalized["enabled"],
                "updated_by_id": actor_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        saved = self.repository.update(updated)
        if bool(payload.get("isDefault") or payload.get("makeDefault")):
            saved = self.repository.set_default(
                name,
                actor_id=actor_id,
                updated_at=datetime.now(timezone.utc),
            )
        return self._public_record(saved)

    def set_default(
        self,
        name: str,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        record = self._require(name)
        if not record.enabled:
            raise ModelConnectionConflict(
                "Only an enabled model connection can be the default."
            )
        saved = self.repository.set_default(
            name,
            actor_id=actor_id,
            updated_at=datetime.now(timezone.utc),
        )
        return self._public_record(saved)

    def delete(self, name: str) -> None:
        record = self._require(name)
        if record.is_default:
            raise ModelConnectionConflict(
                "Choose another default connection before deleting this one."
            )
        self.repository.delete(name)

    def reveal_secret(self, name: str) -> str:
        record = self._require(name)
        secrets = self.cipher.decrypt(name, record.encrypted_api_key)
        return str(secrets.get("apiKey") or "")

    def default_runtime_connection(self) -> ModelRuntimeConnection | None:
        record = next(
            (
                item
                for item in self.repository.list()
                if item.is_default and item.enabled
            ),
            None,
        )
        if not record:
            return None
        return self._runtime_record(record)

    def runtime_connection(self, name: str) -> ModelRuntimeConnection:
        return self._runtime_record(self._require(name))

    def _runtime_record(
        self,
        record: ModelConnectionRecord,
    ) -> ModelRuntimeConnection:
        return ModelRuntimeConnection(
            name=record.name,
            display_name=record.display_name,
            provider_type=record.provider_type,
            model=record.model,
            base_url=record.base_url,
            api_key=self.reveal_secret(record.name),
        )

    def record_test_result(
        self,
        name: str,
        result: dict[str, Any],
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self._require(name)
        updated = ModelConnectionRecord(
            **{
                **existing.__dict__,
                "last_tested_at": datetime.now(timezone.utc),
                "last_test_status": (
                    "ready" if bool(result.get("ok")) else "failed"
                ),
                "last_test_message": str(result.get("message") or ""),
                "updated_by_id": actor_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self._public_record(self.repository.update(updated))

    def _require(self, name: str) -> ModelConnectionRecord:
        record = self.repository.get(name)
        if not record:
            raise ModelConnectionNotFound(
                f"Model connection `{name}` was not found."
            )
        return record

    def _public_record(
        self,
        record: ModelConnectionRecord,
    ) -> dict[str, Any]:
        status = (
            "disabled"
            if not record.enabled
            else record.last_test_status or "untested"
        )
        message = record.last_test_message or (
            "连接尚未检查"
            if record.enabled
            else "连接已停用"
        )
        return {
            "id": record.id,
            "name": record.name,
            "displayName": record.display_name,
            "providerType": record.provider_type,
            "model": record.model,
            "baseUrl": record.base_url,
            "enabled": record.enabled,
            "isDefault": record.is_default,
            "apiKeyConfigured": bool(record.encrypted_api_key),
            "status": status,
            "message": message,
            "lastTestedAt": (
                record.last_tested_at.isoformat()
                if record.last_tested_at
                else None
            ),
            "createdAt": record.created_at.isoformat(),
            "updatedAt": record.updated_at.isoformat(),
        }

    @staticmethod
    def _normalized_input(
        payload: dict[str, Any],
        *,
        creating: bool,
    ) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name or not VALID_CONNECTION_NAME.fullmatch(name):
            raise ModelConnectionError(
                "name must use letters, numbers, underscores, or hyphens."
            )
        display_name = str(payload.get("displayName") or name).strip() or name
        provider_type = str(payload.get("providerType") or "").strip().lower()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ModelConnectionError(
                "providerType must be openai, minimax, or openai_compatible."
            )
        model = str(payload.get("model") or "").strip()
        if not model:
            raise ModelConnectionError("model is required.")
        base_url = str(payload.get("baseUrl") or "").strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ModelConnectionError("baseUrl must be an HTTP(S) URL.")
        api_key = str(payload.get("apiKey") or "")
        if creating and not api_key:
            raise ModelConnectionError("apiKey is required.")
        return {
            "name": name,
            "displayName": display_name,
            "providerType": provider_type,
            "model": model,
            "baseUrl": base_url,
            "apiKey": api_key,
            "enabled": bool(payload.get("enabled", True)),
        }


def legacy_model_connection_from_env(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    explicit_provider = env.get("GENBI_CODEX_PROVIDER", "").strip().lower()
    provider = (
        explicit_provider
        or env.get("GENBI_LLM_PROVIDER", "").strip().lower()
        or "openai"
    )
    provider_type = (
        provider if provider in {"openai", "minimax"} else "openai_compatible"
    )
    model = (
        env.get("GENBI_CODEX_MODEL", "").strip()
        or env.get("GENBI_ANALYSIS_MODEL", "").strip()
        or env.get("MINIMAX_MODEL", "").strip()
        or ("gpt-4.1-mini" if provider_type == "openai" else "")
    )
    if provider_type == "minimax":
        api_key = (
            env.get("GENBI_CODEX_API_KEY", "").strip()
            or env.get("MINIMAX_API_KEY", "").strip()
            or env.get("GENBI_LLM_API_KEY", "").strip()
        )
        base_url = (
            env.get("GENBI_CODEX_BASE_URL", "").strip()
            or env.get("GENBI_MINIMAX_UPSTREAM_BASE_URL", "").strip()
            or env.get("MINIMAX_BASE_URL", "").strip()
            or env.get("GENBI_LLM_BASE_URL", "").strip()
            or "https://api.minimaxi.com/v1"
        )
    else:
        api_key = (
            env.get("GENBI_CODEX_API_KEY", "").strip()
            or env.get("OPENAI_API_KEY", "").strip()
            or env.get("GENBI_LLM_API_KEY", "").strip()
        )
        base_url = (
            env.get("GENBI_CODEX_BASE_URL", "").strip()
            or env.get("OPENAI_BASE_URL", "").strip()
            or env.get("GENBI_LLM_BASE_URL", "").strip()
            or "https://api.openai.com/v1"
        )
    return {
        "name": provider if VALID_CONNECTION_NAME.fullmatch(provider) else "model",
        "displayName": "MiniMax" if provider_type == "minimax" else (
            "OpenAI" if provider_type == "openai" else provider
        ),
        "providerType": provider_type,
        "model": model,
        "baseUrl": base_url.rstrip("/"),
        "apiKey": api_key,
        "enabled": True,
        "isDefault": True,
    }


def legacy_runtime_connection_from_env(
    environ: dict[str, str] | None = None,
) -> ModelRuntimeConnection | None:
    payload = legacy_model_connection_from_env(environ)
    if not str(payload.get("model") or "").strip():
        return None
    if not str(payload.get("apiKey") or "").strip():
        return None
    return ModelRuntimeConnection(
        name=str(payload["name"]),
        display_name=str(payload["displayName"]),
        provider_type=str(payload["providerType"]),
        model=str(payload["model"]),
        base_url=str(payload["baseUrl"]),
        api_key=str(payload["apiKey"]),
        source="environment",
    )


def build_model_connection_registry(
    *,
    import_legacy: bool = True,
) -> ModelConnectionRegistry:
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError(
            "PostgreSQL persistence is required for model connection management."
        )
    master_key = (
        os.getenv("GENBI_MCP_ENCRYPTION_KEY", "").strip()
        or os.getenv("GENBI_SYSTEM_API_TOKEN", "").strip()
    )
    if not master_key:
        raise RuntimeError(
            "GENBI_MCP_ENCRYPTION_KEY or GENBI_SYSTEM_API_TOKEN is required."
        )
    registry = ModelConnectionRegistry(
        repository=PostgresModelConnectionRepository(database_url),
        cipher=McpSecretCipher(master_key),
    )
    if import_legacy and not registry.repository.list():
        legacy = legacy_model_connection_from_env()
        if legacy.get("model") and legacy.get("apiKey"):
            registry.create(legacy, actor_id="system-import")
    return registry


def try_build_model_connection_registry(
    *,
    import_legacy: bool = True,
) -> ModelConnectionRegistry | None:
    try:
        registry = build_model_connection_registry(import_legacy=import_legacy)
        registry.repository.list()
        return registry
    except Exception as error:
        LOGGER.warning("model_connection_registry_fallback error=%s", error)
        return None


def resolve_default_model_connection() -> ModelRuntimeConnection | None:
    registry = try_build_model_connection_registry()
    if registry is not None:
        managed = registry.default_runtime_connection()
        if managed is not None:
            return managed
    return legacy_runtime_connection_from_env()
