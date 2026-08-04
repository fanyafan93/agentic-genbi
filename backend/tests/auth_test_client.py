"""Helpers for unit tests that need an authenticated ``TestClient``.

The authentication layer resolves a :class:`Principal` from either a real
Auth.js session cookie or a development-only ``X-Genbi-Test-Principal``
header. Tests that don't care about identity can use :func:`auth_client`
which enables the development bypass and returns a lightweight wrapper that
remembers a default principal and exposes per-call overrides.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from backend.api.principal import (
    AUTH_PRINCIPAL_HEADER,
    DEFAULT_TENANT_ID,
    enable_dev_principal_bypass,
)

DEFAULT_TEST_USER_ID = "test_user"
DEFAULT_TEST_TENANT_ID = DEFAULT_TENANT_ID


def _principal_header(user_id: str, tenant_id: str = DEFAULT_TEST_TENANT_ID, role: str = "user") -> dict[str, str]:
    return {AUTH_PRINCIPAL_HEADER: json.dumps({"user_id": user_id, "tenant_id": tenant_id, "role": role})}


def _ensure_test_client_default_principal_patch() -> None:
    """Attach ``X-Genbi-Test-Principal`` to every ``TestClient`` request.

    Tests opt into identity by overriding headers explicitly; tests that
    don't care default to ``test_user``. The patch is applied at most once
    per process so multiple test modules can share it safely.
    """

    marker = "__genbi_principal_patched__"
    if getattr(TestClient.request, marker, False):
        return
    original_request = TestClient.request

    def patched_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if getattr(self, "__genbi_skip_principal__", False):
            return original_request(self, *args, **kwargs)
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault(AUTH_PRINCIPAL_HEADER, _principal_header(DEFAULT_TEST_USER_ID)[AUTH_PRINCIPAL_HEADER])
        kwargs["headers"] = headers
        return original_request(self, *args, **kwargs)

    patched_request.__dict__[marker] = True  # type: ignore[attr-defined]
    TestClient.request = patched_request  # type: ignore[assignment]


_ensure_test_client_default_principal_patch()


def _bypass_principal_for_anonymous_request(client: TestClient) -> None:
    """Allow a single ``TestClient`` instance to skip the auto-injected
    principal header. Used by tests that need to exercise 401 responses.
    """

    # The patched ``TestClient.request`` honours an opt-out attribute on the
    # instance. We toggle it here so the wrapper can route around the
    # default ``test_user`` injection.
    setattr(client, "__genbi_skip_principal__", True)


class AuthTestClient:
    """Wrapper around ``fastapi.testclient.TestClient`` that injects principals."""

    def __init__(
        self,
        app: Any,
        *,
        user_id: str = DEFAULT_TEST_USER_ID,
        tenant_id: str = DEFAULT_TEST_TENANT_ID,
        role: str = "user",
    ) -> None:
        self._client = TestClient(app)
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._role = role

    def _with_identity(self, headers: dict[str, str] | None, *, user_id: str | None = None, tenant_id: str | None = None, role: str | None = None) -> dict[str, str]:
        merged = dict(headers or {})
        effective_user = user_id if user_id is not None else self._user_id
        effective_tenant = tenant_id if tenant_id is not None else self._tenant_id
        effective_role = role if role is not None else self._role
        principal_header = _principal_header(effective_user, tenant_id=effective_tenant, role=effective_role)
        merged.update(principal_header)
        return merged

    def get(self, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
        url = path if not params else f"{path}?{urlencode(params)}"
        return self._client.get(url, headers=self._with_identity(headers), **kwargs)

    def post(self, path: str, *, json: Any = None, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
        return self._client.post(path, json=json, headers=self._with_identity(headers), **kwargs)

    def patch(self, path: str, *, json: Any = None, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
        return self._client.patch(path, json=json, headers=self._with_identity(headers), **kwargs)

    def delete(self, path: str, *, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
        return self._client.delete(path, headers=self._with_identity(headers), **kwargs)

    def as_user(self, *, user_id: str, tenant_id: str = DEFAULT_TEST_TENANT_ID, role: str = "user") -> "AuthTestClient":
        clone = AuthTestClient.__new__(AuthTestClient)
        clone._client = self._client
        clone._user_id = user_id
        clone._tenant_id = tenant_id
        clone._role = role
        return clone


@contextmanager
def auth_client(
    app: Any,
    *,
    user_id: str = DEFAULT_TEST_USER_ID,
    tenant_id: str = DEFAULT_TEST_TENANT_ID,
    role: str = "user",
) -> Iterator[AuthTestClient]:
    enable_dev_principal_bypass(True)
    try:
        yield AuthTestClient(app, user_id=user_id, tenant_id=tenant_id, role=role)
    finally:
        enable_dev_principal_bypass(False)


def build_test_app(
    *,
    analysis_runtime: Any = None,
    knowledge_store: Any = "auto",
    thread_store: Any = "auto",
    analysis_asset_store: Any = "auto",
    interactive_report_store: Any = "auto",
    finereport_repository: Any = None,
) -> Any:
    """Construct a FastAPI app wired with in-memory stores.

    Production code paths now require Postgres at boot; tests that
    want to exercise the API without standing up a database must
    inject every store explicitly. This helper wires empty in-memory
    stores for the caller so the test reads as a single line.

    Pass any of the store arguments as ``None`` to force the
    default-construction branch (which now requires Postgres). The
    string sentinel ``"auto"`` is the default and means "use a
    fresh in-memory store"; pass ``None`` to exercise the
    Postgres-required default.
    """
    from backend.analysis.asset_store import AnalysisAssetStore
    from backend.analysis.interactive_report_store import InteractiveReportStore
    from backend.business_semantics.knowledge_store import KnowledgeStore
    from backend.harness.thread_store import ThreadStore
    from backend.api.analysis_api import create_app

    def _resolve(sentinel: Any, default_factory: Any) -> Any:
        if sentinel == "auto":
            return default_factory()
        return sentinel

    return create_app(
        analysis_runtime=analysis_runtime,
        knowledge_store=_resolve(knowledge_store, KnowledgeStore),
        analysis_asset_store=_resolve(analysis_asset_store, AnalysisAssetStore),
        interactive_report_store=_resolve(interactive_report_store, InteractiveReportStore),
        thread_store=_resolve(thread_store, ThreadStore),
        finereport_repository=finereport_repository,
    )


def anonymous_client(app: Any) -> AuthTestClient:
    """Return a wrapper whose requests carry no session and no dev principal.

    Useful when the test wants to verify that the API rejects anonymous
    callers with 401 instead of dispatching through the dev fallback. The
    wrapper opts out of the auto-injected ``X-Genbi-Test-Principal`` header
    so the request only sees what the real Auth.js session would have
    exposed; with no cookie in the test env, the backend responds with 401.
    """

    client = TestClient(app)
    _bypass_principal_for_anonymous_request(client)
    wrapper = AuthTestClient.__new__(AuthTestClient)
    wrapper._client = client
    wrapper._user_id = ""
    wrapper._tenant_id = ""
    wrapper._role = ""
    return wrapper
