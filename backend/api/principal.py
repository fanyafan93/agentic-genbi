"""Logged-in principal resolution for the Agentic GenBI backend.

The backend is the source of truth for identity. Every request that touches a
user-owned resource (analysis thread, turn, item, interactive report, share,
analysis asset, knowledge record, etc.) must resolve a :class:`Principal` from
the active login session and apply tenant + user filters automatically.

The session is the Auth.js (NextAuth) database session living in the same
Postgres instance used by the frontend ``prisma`` schema. The browser sends the
``next-auth.session-token`` (or ``__Secure-next-auth.session-token``) cookie;
the backend looks it up, joins with ``"User"`` and returns
``(user_id, tenant_id, role)``. Tenant is a per-user column in this slice so
that the boundary moves with the user, not the request. If the column is
missing we fall back to ``"default"`` and log a warning so the operator can
backfill tenants later.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from backend.persistence.postgres_stores import _connect, get_postgres_database_url

_LOG = logging.getLogger(__name__)

AUTH_SESSION_COOKIE_NAME = "next-auth.session-token"
AUTH_SECURE_SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
AUTH_PRINCIPAL_HEADER = "x-genbi-test-principal"
AUTH_DEV_BYPASS_ENV = "GENBI_AUTH_DEV_BYPASS"

# Tenant fallback: until teams/onboarding is wired, every user lives under a
# single shared tenant. The column is kept first-class so a real tenant can be
# added without changing call sites.
DEFAULT_TENANT_ID = "default"


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str
    session_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role in {"admin", "platform_admin"}


@dataclass(frozen=True)
class UnauthenticatedPrincipal:
    user_id: str = "anonymous"
    tenant_id: str = DEFAULT_TENANT_ID
    role: str = "anonymous"
    session_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return False


ANY_PRINCIPAL = UnauthenticatedPrincipal()


def _read_session_token(request: Request) -> str | None:
    for name in (AUTH_SECURE_SESSION_COOKIE_NAME, AUTH_SESSION_COOKIE_NAME):
        value = request.cookies.get(name)
        if value:
            return value
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            return token
    return None


def _resolve_session_principal(session_token: str) -> Principal | None:
    """Look up the Auth.js session row and return a :class:`Principal`.

    Returns ``None`` when the cookie is missing/expired/unknown. Callers should
    map that to HTTP 401; never to an anonymous default.
    """

    database_url = get_postgres_database_url()
    if not database_url:
        return None
    try:
        with _connect(database_url) as conn:
            row = conn.execute(
                """
                SELECT s."sessionToken" AS session_token,
                       s."expires" AS expires,
                       u."id" AS user_id,
                       u."role" AS role,
                       COALESCE(NULLIF(u."email", ''), u."id") AS tenant_id
                FROM "Session" AS s
                JOIN "User" AS u ON u."id" = s."userId"
                WHERE s."sessionToken" = %(token)s
                """,
                {"token": session_token},
            ).fetchone()
    except Exception as exc:  # pragma: no cover - connection errors should surface
        _LOG.warning("principal_lookup_db_error: %s", exc)
        return None
    if not row:
        return None
    expires = row.get("expires")
    if expires is not None:
        try:
            from datetime import datetime
            if isinstance(expires, datetime) and expires < datetime.utcnow().replace(tzinfo=expires.tzinfo):
                return None
        except Exception:
            pass
    role = (row.get("role") or "user").strip() or "user"
    tenant_id = (row.get("tenant_id") or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
    return Principal(
        user_id=str(row.get("user_id") or "").strip(),
        tenant_id=tenant_id,
        role=role,
        session_id=str(row.get("session_token") or "").strip() or None,
    )


def _parse_dev_principal(header_value: str) -> Principal | None:
    """Parse a development-only principal from the ``X-Genbi-Test-Principal`` header.

    The header is only honored when ``GENBI_AUTH_DEV_BYPASS`` is set to a truthy
    value (``1`` / ``true`` / ``yes``). It is used by unit tests and local
    smoke tests. Production deploys must leave the env variable unset so this
    path becomes a no-op.
    """

    if not _is_dev_bypass_enabled():
        return None
    try:
        payload = json.loads(header_value)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    user_id = str(payload.get("user_id") or payload.get("userId") or "").strip()
    if not user_id:
        return None
    tenant_id = str(payload.get("tenant_id") or payload.get("tenantId") or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
    role = str(payload.get("role") or "user").strip() or "user"
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)


_DEV_BYPASS_STATE: dict[str, bool] = {"enabled": False}


def enable_dev_principal_bypass(enabled: bool = True) -> None:
    """Test-only flag; lets unit tests bypass real Postgres sessions.

    Production paths check ``os.getenv`` so this in-memory flag cannot leak
    into runtime deployments. Always pair with a ``try`` / ``finally`` (or a
    context manager) so the flag is restored at the end of the test.
    """

    _DEV_BYPASS_STATE["enabled"] = bool(enabled)


def _is_dev_bypass_enabled() -> bool:
    if _DEV_BYPASS_STATE["enabled"]:
        return True
    return os.getenv(AUTH_DEV_BYPASS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_principal(request: Request) -> Principal | None:
    """Resolve the request principal, or ``None`` if the request is anonymous.

    Order:
        1. Development test bypass header (only when explicitly enabled).
        2. Auth.js session cookie backed by Postgres.
    """

    dev_header = request.headers.get(AUTH_PRINCIPAL_HEADER)
    if dev_header and _is_dev_bypass_enabled():
        parsed = _parse_dev_principal(dev_header)
        if parsed:
            return parsed
    token = _read_session_token(request)
    if not token:
        return None
    return _resolve_session_principal(token)


def require_principal(request: Request) -> Principal:
    principal = resolve_principal(request)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
            headers={"WWW-Authenticate": 'Bearer realm="agentic-genbi"'},
        )
    return principal


def _default_dev_principal(request: Request) -> Principal:  # pragma: no cover - kept for future use
    user_id = "test_user"
    tenant_id = DEFAULT_TENANT_ID
    role = "user"
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)


def require_admin(principal: Principal) -> None:
    """Raise 403 unless the principal carries an admin role.

    Admin powers must come from the backend; any UI hint is decorative.
    """

    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin_role_required",
        )


def principal_metadata(principal: Principal) -> dict[str, Any]:
    """Return the ``tenant_id`` / ``workspace_id`` shape that the thread layer
    already understands. Keeping this in one place stops drift across endpoints.
    """

    return {"tenant_id": principal.tenant_id, "workspace_id": principal.tenant_id}


__all__ = [
    "ANY_PRINCIPAL",
    "AUTH_DEV_BYPASS_ENV",
    "AUTH_PRINCIPAL_HEADER",
    "AUTH_SESSION_COOKIE_NAME",
    "AUTH_SECURE_SESSION_COOKIE_NAME",
    "DEFAULT_TENANT_ID",
    "Principal",
    "UnauthenticatedPrincipal",
    "enable_dev_principal_bypass",
    "principal_metadata",
    "require_admin",
    "require_principal",
    "resolve_principal",
]
