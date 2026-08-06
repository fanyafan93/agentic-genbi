from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.mcp_servers.genbi_report_build_tools import (
    report_build_tool_schemas,
)
from backend.persistence.postgres_stores import get_postgres_database_url


SYSTEM_MCP_NAME = "GenBI_report"
SECRET_MASK = "••••••••"
VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class McpRegistryError(ValueError):
    pass


class McpRegistryConflict(McpRegistryError):
    pass


class McpRegistryNotFound(McpRegistryError):
    pass


@dataclass
class McpServerRecord:
    id: str
    name: str
    display_name: str
    transport: str
    config: dict[str, Any]
    encrypted_secrets: str
    enabled: bool
    created_by_id: str
    updated_by_id: str
    created_at: datetime
    updated_at: datetime
    discovered_tools: list[dict[str, Any]] = field(default_factory=list)
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None


class McpServerRepository(Protocol):
    def list(self) -> list[McpServerRecord]: ...

    def get(self, name: str) -> McpServerRecord | None: ...

    def create(self, record: McpServerRecord) -> McpServerRecord: ...

    def update(self, record: McpServerRecord) -> McpServerRecord: ...

    def delete(self, name: str) -> None: ...


class MemoryMcpServerRepository:
    def __init__(self) -> None:
        self.records: dict[str, McpServerRecord] = {}

    def list(self) -> list[McpServerRecord]:
        return [deepcopy(record) for record in self.records.values()]

    def get(self, name: str) -> McpServerRecord | None:
        record = self.records.get(name)
        return deepcopy(record) if record else None

    def create(self, record: McpServerRecord) -> McpServerRecord:
        if record.name in self.records:
            raise McpRegistryConflict(f"MCP server `{record.name}` already exists.")
        self.records[record.name] = deepcopy(record)
        return deepcopy(record)

    def update(self, record: McpServerRecord) -> McpServerRecord:
        if record.name not in self.records:
            raise McpRegistryNotFound(f"MCP server `{record.name}` was not found.")
        self.records[record.name] = deepcopy(record)
        return deepcopy(record)

    def delete(self, name: str) -> None:
        if name not in self.records:
            raise McpRegistryNotFound(f"MCP server `{name}` was not found.")
        del self.records[name]


class PostgresMcpServerRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def list(self) -> list[McpServerRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM "McpServer"
                ORDER BY name
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, name: str) -> McpServerRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM "McpServer"
                WHERE name = %s
                """,
                (name,),
            ).fetchone()
        return self._from_row(row) if row else None

    def create(self, record: McpServerRecord) -> McpServerRecord:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    INSERT INTO "McpServer" (
                        id, name, "displayName", transport, config,
                        "encryptedSecrets", enabled, "createdById", "updatedById",
                        "createdAt", "updatedAt", "discoveredTools",
                        "lastTestedAt", "lastTestStatus", "lastTestMessage"
                    )
                    VALUES (
                        %s, %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s,
                        %s, %s, %s::jsonb,
                        %s, %s, %s
                    )
                    RETURNING *
                    """,
                    self._values(record),
                ).fetchone()
        except Exception as error:
            if getattr(error, "sqlstate", "") == "23505":
                raise McpRegistryConflict(
                    f"MCP server `{record.name}` already exists."
                ) from error
            raise
        return self._from_row(row)

    def update(self, record: McpServerRecord) -> McpServerRecord:
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE "McpServer"
                SET
                    "displayName" = %s,
                    transport = %s,
                    config = %s::jsonb,
                    "encryptedSecrets" = %s,
                    enabled = %s,
                    "updatedById" = %s,
                    "updatedAt" = %s,
                    "discoveredTools" = %s::jsonb,
                    "lastTestedAt" = %s,
                    "lastTestStatus" = %s,
                    "lastTestMessage" = %s
                WHERE name = %s
                RETURNING *
                """,
                (
                    record.display_name,
                    record.transport,
                    json.dumps(record.config, ensure_ascii=False),
                    record.encrypted_secrets,
                    record.enabled,
                    record.updated_by_id,
                    record.updated_at,
                    json.dumps(record.discovered_tools, ensure_ascii=False),
                    record.last_tested_at,
                    record.last_test_status,
                    record.last_test_message,
                    record.name,
                ),
            ).fetchone()
        if not row:
            raise McpRegistryNotFound(f"MCP server `{record.name}` was not found.")
        return self._from_row(row)

    def delete(self, name: str) -> None:
        with self._connection() as connection:
            row = connection.execute(
                """
                DELETE FROM "McpServer"
                WHERE name = %s
                RETURNING name
                """,
                (name,),
            ).fetchone()
        if not row:
            raise McpRegistryNotFound(f"MCP server `{name}` was not found.")

    def _connection(self) -> Any:
        from psycopg import connect
        from psycopg.rows import dict_row

        return connect(self.database_url, row_factory=dict_row)

    def _values(self, record: McpServerRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.name,
            record.display_name,
            record.transport,
            json.dumps(record.config, ensure_ascii=False),
            record.encrypted_secrets,
            record.enabled,
            record.created_by_id,
            record.updated_by_id,
            record.created_at,
            record.updated_at,
            json.dumps(record.discovered_tools, ensure_ascii=False),
            record.last_tested_at,
            record.last_test_status,
            record.last_test_message,
        )

    def _from_row(self, row: dict[str, Any]) -> McpServerRecord:
        return McpServerRecord(
            id=str(row["id"]),
            name=str(row["name"]),
            display_name=str(row["displayName"]),
            transport=str(row["transport"]),
            config=_json_object(row.get("config")),
            encrypted_secrets=str(row.get("encryptedSecrets") or ""),
            enabled=bool(row.get("enabled")),
            created_by_id=str(row.get("createdById") or ""),
            updated_by_id=str(row.get("updatedById") or ""),
            created_at=row["createdAt"],
            updated_at=row["updatedAt"],
            discovered_tools=_json_list(row.get("discoveredTools")),
            last_tested_at=row.get("lastTestedAt"),
            last_test_status=(
                str(row["lastTestStatus"]) if row.get("lastTestStatus") else None
            ),
            last_test_message=(
                str(row["lastTestMessage"]) if row.get("lastTestMessage") else None
            ),
        )


class McpSecretCipher:
    """Versioned AES-256-GCM envelope for MCP credentials."""

    def __init__(self, master_key: str) -> None:
        if not master_key.strip():
            raise ValueError("An MCP encryption master key is required.")
        self._key = hashlib.sha256(master_key.encode("utf-8")).digest()

    def encrypt(self, server_name: str, secrets: dict[str, str]) -> str:
        if not secrets:
            return ""
        nonce = os.urandom(12)
        plaintext = json.dumps(
            secrets,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            plaintext,
            server_name.encode("utf-8"),
        )
        return "v1:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, server_name: str, envelope: str) -> dict[str, str]:
        if not envelope:
            return {}
        if not envelope.startswith("v1:"):
            raise ValueError("Unsupported MCP secret envelope.")
        raw = base64.urlsafe_b64decode(envelope[3:].encode("ascii"))
        try:
            plaintext = AESGCM(self._key).decrypt(
                raw[:12],
                raw[12:],
                server_name.encode("utf-8"),
            )
        except Exception as error:
            raise ValueError("MCP secret envelope could not be decrypted.") from error
        decoded = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Invalid MCP secret payload.")
        return {str(key): str(value) for key, value in decoded.items()}


class McpRegistry:
    def __init__(
        self,
        *,
        repository: McpServerRepository,
        cipher: McpSecretCipher,
        system_enabled: bool = True,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.system_enabled = system_enabled

    def list(self) -> list[dict[str, Any]]:
        external = [
            self._public_record(record)
            for record in sorted(self.repository.list(), key=lambda item: item.name.lower())
        ]
        return [self._system_payload(), *external]

    def get(self, name: str) -> dict[str, Any]:
        if name == SYSTEM_MCP_NAME:
            return self._system_payload()
        record = self.repository.get(name)
        if not record:
            raise McpRegistryNotFound(f"MCP server `{name}` was not found.")
        return self._public_record(record)

    def create(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        normalized = self._normalized_input(payload, creating=True)
        name = normalized["name"]
        if name == SYSTEM_MCP_NAME:
            raise McpRegistryConflict(f"`{SYSTEM_MCP_NAME}` is reserved by the system.")
        if self.repository.get(name):
            raise McpRegistryConflict(f"MCP server `{name}` already exists.")
        now = datetime.now(timezone.utc)
        record = McpServerRecord(
            id=uuid.uuid4().hex,
            name=name,
            display_name=normalized["displayName"],
            transport=normalized["transport"],
            config=normalized["config"],
            encrypted_secrets=self.cipher.encrypt(name, normalized["secrets"]),
            enabled=normalized["enabled"],
            created_by_id=actor_id,
            updated_by_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        return self._public_record(self.repository.create(record))

    def update(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        if name == SYSTEM_MCP_NAME:
            raise McpRegistryConflict("System MCP configuration is code-owned.")
        if "name" in payload and str(payload["name"]).strip() != name:
            raise McpRegistryConflict("MCP server name is immutable.")
        existing = self.repository.get(name)
        if not existing:
            raise McpRegistryNotFound(f"MCP server `{name}` was not found.")
        current_payload = self._editable_payload(existing)
        merged = {**current_payload, **payload, "name": name}
        normalized = self._normalized_input(merged, creating=False)
        secrets = self.cipher.decrypt(name, existing.encrypted_secrets)
        incoming_secrets = normalized.pop("incomingSecrets")
        for key, value in incoming_secrets.items():
            if value:
                secrets[key] = value
        configured_secret_keys = set(normalized["secretKeys"])
        secrets = {
            key: value for key, value in secrets.items() if key in configured_secret_keys
        }
        record = McpServerRecord(
            **{
                **existing.__dict__,
                "display_name": normalized["displayName"],
                "transport": normalized["transport"],
                "config": normalized["config"],
                "encrypted_secrets": self.cipher.encrypt(name, secrets),
                "enabled": normalized["enabled"],
                "updated_by_id": actor_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self._public_record(self.repository.update(record))

    def set_enabled(
        self,
        name: str,
        enabled: bool,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        if name == SYSTEM_MCP_NAME:
            self.system_enabled = enabled
            return self._system_payload()
        return self.update(name, {"enabled": enabled}, actor_id=actor_id)

    def delete(self, name: str) -> None:
        if name == SYSTEM_MCP_NAME:
            raise McpRegistryConflict("System MCP cannot be deleted.")
        self.repository.delete(name)

    def reveal_secrets(self, name: str) -> dict[str, str]:
        if name == SYSTEM_MCP_NAME:
            return {}
        record = self.repository.get(name)
        if not record:
            raise McpRegistryNotFound(f"MCP server `{name}` was not found.")
        return self.cipher.decrypt(name, record.encrypted_secrets)

    def runtime_servers(self, *, include_disabled: bool = False) -> list[Any]:
        from backend.harness.codex_mcp_config import CodexMcpServer

        servers: list[CodexMcpServer] = []
        if self.system_enabled or include_disabled:
            servers.append(
                CodexMcpServer(
                    name=SYSTEM_MCP_NAME,
                    transport="stdio",
                    command="python",
                    args=["-m", "backend.mcp_servers.genbi_report_server"],
                )
            )
        for record in self.repository.list():
            if not record.enabled and not include_disabled:
                continue
            secrets = self.cipher.decrypt(record.name, record.encrypted_secrets)
            config = record.config
            environment = dict(config.get("environment") or {})
            environment.update(secrets)
            bearer_env_var = str(config.get("bearerTokenEnvVar") or "")
            runtime_env = (
                {bearer_env_var: secrets[bearer_env_var]}
                if bearer_env_var and bearer_env_var in secrets
                else {}
            )
            servers.append(
                CodexMcpServer(
                    name=record.name,
                    transport=record.transport,
                    command=str(config.get("command") or ""),
                    args=[str(value) for value in config.get("args") or []],
                    env=environment if record.transport == "stdio" else {},
                    url=str(config.get("url") or ""),
                    bearer_token_env_var=bearer_env_var,
                    oauth_client_id=str(config.get("oauthClientId") or ""),
                    oauth_resource=str(config.get("oauthResource") or ""),
                    runtime_env=runtime_env,
                )
            )
        return servers

    def runtime_server(self, name: str) -> Any:
        server = next(
            (
                item
                for item in self.runtime_servers(include_disabled=True)
                if item.name == name
            ),
            None,
        )
        if server is None:
            raise McpRegistryNotFound(f"MCP server `{name}` was not found.")
        return server

    def record_test_result(
        self,
        name: str,
        result: dict[str, Any],
        *,
        actor_id: str,
    ) -> None:
        if name == SYSTEM_MCP_NAME:
            return
        existing = self.repository.get(name)
        if not existing:
            raise McpRegistryNotFound(f"MCP server `{name}` was not found.")
        updated = McpServerRecord(
            **{
                **existing.__dict__,
                "discovered_tools": [
                    dict(tool)
                    for tool in result.get("tools") or []
                    if isinstance(tool, dict)
                ],
                "last_tested_at": datetime.now(timezone.utc),
                "last_test_status": str(result.get("status") or "unavailable"),
                "last_test_message": str(result.get("message") or ""),
                "updated_by_id": actor_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.repository.update(updated)

    def upgrade_plaintext_secret_fields(self) -> None:
        """Move legacy secret-like environment values into the encrypted envelope."""
        for existing in self.repository.list():
            config = deepcopy(existing.config)
            environment = dict(config.get("environment") or {})
            secret_keys = set(config.get("secretKeys") or [])
            keys_to_move = [
                key
                for key in environment
                if key not in secret_keys and _looks_secret(key)
            ]
            if not keys_to_move:
                continue
            secrets = self.cipher.decrypt(
                existing.name,
                existing.encrypted_secrets,
            )
            for key in keys_to_move:
                secrets[key] = str(environment.pop(key))
                secret_keys.add(key)
            config["environment"] = environment
            config["secretKeys"] = sorted(secret_keys)
            now = datetime.now(timezone.utc)
            self.repository.update(
                McpServerRecord(
                    **{
                        **existing.__dict__,
                        "config": config,
                        "encrypted_secrets": self.cipher.encrypt(
                            existing.name,
                            secrets,
                        ),
                        "updated_by_id": "system-security-upgrade",
                        "updated_at": now,
                    }
                )
            )

    def _system_payload(self) -> dict[str, Any]:
        return {
            "name": SYSTEM_MCP_NAME,
            "displayName": "GenBI Report",
            "category": "system",
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "backend.mcp_servers.genbi_report_server"],
            "url": "",
            "bearerTokenEnvVar": "",
            "oauthClientId": "",
            "oauthResource": "",
            "environment": [],
            "enabled": self.system_enabled,
            "mutable": False,
            "deletable": False,
            "status": "trusted",
            "permission": "report.write",
            "trusted": True,
            "approval": "trusted",
            "tools": [
                {
                    "name": str(tool["name"]),
                    "description": str(tool["description"]),
                    "permission": "report.write",
                    "trusted": True,
                }
                for tool in report_build_tool_schemas()
            ],
            "envKeys": [],
            "message": "System-built-in Report configuration tool.",
        }

    def _public_record(self, record: McpServerRecord) -> dict[str, Any]:
        config = record.config
        secret_keys = set(config.get("secretKeys") or [])
        environment = [
            {
                "key": key,
                "value": SECRET_MASK if key in secret_keys else str(value),
                "secret": key in secret_keys,
                "configured": key in secret_keys,
            }
            for key, value in sorted((config.get("environment") or {}).items())
        ]
        for key in sorted(secret_keys - {item["key"] for item in environment}):
            environment.append(
                {
                    "key": key,
                    "value": SECRET_MASK,
                    "secret": True,
                    "configured": True,
                }
            )
        return {
            "name": record.name,
            "displayName": record.display_name,
            "category": "external",
            "transport": record.transport,
            "command": str(config.get("command") or ""),
            "args": list(config.get("args") or []),
            "url": str(config.get("url") or ""),
            "bearerTokenEnvVar": str(config.get("bearerTokenEnvVar") or ""),
            "oauthClientId": str(config.get("oauthClientId") or ""),
            "oauthResource": str(config.get("oauthResource") or ""),
            "environment": environment,
            "enabled": record.enabled,
            "mutable": True,
            "deletable": True,
            "status": record.last_test_status or "configured",
            "permission": "tool.external",
            "trusted": False,
            "approval": "required",
            "tools": deepcopy(record.discovered_tools),
            "envKeys": sorted(
                set((config.get("environment") or {}).keys()) | secret_keys
            ),
            "message": record.last_test_message or "External MCP is configured.",
            "createdById": record.created_by_id,
            "updatedById": record.updated_by_id,
            "createdAt": record.created_at.isoformat(),
            "updatedAt": record.updated_at.isoformat(),
            "lastTestedAt": (
                record.last_tested_at.isoformat() if record.last_tested_at else None
            ),
        }

    def _editable_payload(self, record: McpServerRecord) -> dict[str, Any]:
        config = record.config
        secret_keys = set(config.get("secretKeys") or [])
        environment = [
            {
                "key": key,
                "value": "" if key in secret_keys else str(value),
                "secret": key in secret_keys,
            }
            for key, value in (config.get("environment") or {}).items()
        ]
        for key in secret_keys - {item["key"] for item in environment}:
            if key != config.get("bearerTokenEnvVar"):
                environment.append({"key": key, "value": "", "secret": True})
        return {
            "name": record.name,
            "displayName": record.display_name,
            "transport": record.transport,
            "command": str(config.get("command") or ""),
            "args": list(config.get("args") or []),
            "url": str(config.get("url") or ""),
            "bearerTokenEnvVar": str(config.get("bearerTokenEnvVar") or ""),
            "bearerToken": "",
            "oauthClientId": str(config.get("oauthClientId") or ""),
            "oauthResource": str(config.get("oauthResource") or ""),
            "environment": environment,
            "enabled": record.enabled,
        }

    def _normalized_input(
        self,
        payload: dict[str, Any],
        *,
        creating: bool,
    ) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name or not VALID_NAME.fullmatch(name):
            raise McpRegistryError(
                "MCP server name may only contain letters, numbers, `_` and `-`."
            )
        display_name = str(payload.get("displayName") or name).strip() or name
        transport = str(payload.get("transport") or "stdio").strip()
        if transport not in {"stdio", "streamable_http"}:
            raise McpRegistryError("transport must be `stdio` or `streamable_http`.")
        command = str(payload.get("command") or "").strip()
        url = str(payload.get("url") or "").strip()
        if transport == "stdio" and not command:
            raise McpRegistryError("stdio MCP requires a command.")
        if transport == "streamable_http" and not url:
            raise McpRegistryError("streamable HTTP MCP requires a URL.")
        args_raw = payload.get("args") or []
        if not isinstance(args_raw, list):
            raise McpRegistryError("args must be a list.")
        environment_raw = payload.get("environment") or []
        if not isinstance(environment_raw, list):
            raise McpRegistryError("environment must be a list.")
        environment: dict[str, str] = {}
        secret_keys: set[str] = set()
        incoming_secrets: dict[str, str] = {}
        for item in environment_raw:
            if not isinstance(item, dict):
                raise McpRegistryError("environment entries must be objects.")
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            value = str(item.get("value") or "")
            if bool(item.get("secret")):
                secret_keys.add(key)
                incoming_secrets[key] = value
            else:
                environment[key] = value
        bearer_env_var = str(payload.get("bearerTokenEnvVar") or "").strip()
        bearer_token = str(payload.get("bearerToken") or "")
        if bearer_env_var:
            secret_keys.add(bearer_env_var)
            incoming_secrets[bearer_env_var] = bearer_token
        secrets = {
            key: value for key, value in incoming_secrets.items() if value
        }
        config = {
            "command": command if transport == "stdio" else "",
            "args": [str(value) for value in args_raw] if transport == "stdio" else [],
            "url": url if transport == "streamable_http" else "",
            "bearerTokenEnvVar": (
                bearer_env_var if transport == "streamable_http" else ""
            ),
            "oauthClientId": (
                str(payload.get("oauthClientId") or "").strip()
                if transport == "streamable_http"
                else ""
            ),
            "oauthResource": (
                str(payload.get("oauthResource") or "").strip()
                if transport == "streamable_http"
                else ""
            ),
            "environment": environment,
            "secretKeys": sorted(secret_keys),
        }
        normalized = {
            "name": name,
            "displayName": display_name,
            "transport": transport,
            "config": config,
            "secrets": secrets,
            "incomingSecrets": incoming_secrets,
            "secretKeys": sorted(secret_keys),
            "enabled": bool(payload.get("enabled", True)),
        }
        if creating:
            normalized.pop("incomingSecrets")
            normalized.pop("secretKeys")
        return normalized


def build_mcp_registry(*, import_legacy: bool = True) -> McpRegistry:
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("PostgreSQL persistence is required for MCP management.")
    master_key = (
        os.getenv("GENBI_MCP_ENCRYPTION_KEY", "").strip()
        or os.getenv("GENBI_SYSTEM_API_TOKEN", "").strip()
    )
    if not master_key:
        raise RuntimeError(
            "GENBI_MCP_ENCRYPTION_KEY or GENBI_SYSTEM_API_TOKEN is required."
        )
    from backend.system_management.settings_store import mcp_enabled_overrides

    enabled_overrides = mcp_enabled_overrides()
    registry = McpRegistry(
        repository=PostgresMcpServerRepository(database_url),
        cipher=McpSecretCipher(master_key),
        system_enabled=enabled_overrides.get(SYSTEM_MCP_NAME, True),
    )
    registry.upgrade_plaintext_secret_fields()
    if import_legacy:
        _import_legacy_servers(registry, enabled_overrides=enabled_overrides)
    return registry


def try_build_mcp_registry(*, import_legacy: bool = True) -> McpRegistry | None:
    try:
        registry = build_mcp_registry(import_legacy=import_legacy)
        registry.repository.list()
        return registry
    except Exception:
        return None


def _import_legacy_servers(
    registry: McpRegistry,
    *,
    enabled_overrides: dict[str, bool],
) -> None:
    from backend.harness.codex_mcp_config import load_codex_mcp_servers_from_env

    for server in load_codex_mcp_servers_from_env():
        if server.name == SYSTEM_MCP_NAME or registry.repository.get(server.name):
            continue
        environment = [
            {
                "key": key,
                "value": value,
                "secret": _looks_secret(key),
            }
            for key, value in server.env.items()
        ]
        registry.create(
            {
                "name": server.name,
                "displayName": server.name,
                "transport": server.transport,
                "command": server.command,
                "args": server.args,
                "environment": environment,
                "enabled": enabled_overrides.get(server.name, True),
            },
            actor_id="system-import",
        )


def _looks_secret(key: str) -> bool:
    upper = key.upper()
    return any(
        marker in upper
        for marker in ("PASSWORD", "TOKEN", "SECRET", "API_KEY", "PRIVATE_KEY")
    ) or upper == "PASS" or upper.endswith("_PASS")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        decoded = json.loads(value)
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def _json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str) and value:
        value = json.loads(value)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
