from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import secrets
from threading import RLock

from backend.reports.build_service import (
    REPORT_BUILD_TOOL_NAMES,
    ReportBuildContext,
)


class ReportToolTokenError(PermissionError):
    pass


@dataclass
class _ExecutionState:
    owner_id: str
    tenant_id: str | None
    workspace_id: str | None
    roles: tuple[str, ...]
    expires_at: int
    session_id: str | None = None
    turn_id: str | None = None
    report_started: bool = False
    report_published: bool = False
    no_progress_rounds: int = 0
    correction_read_available: bool = False


class ReportToolExecutionRegistry:
    def __init__(
        self,
        *,
        secret: bytes | None = None,
        ttl: timedelta = timedelta(hours=1),
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._ttl = ttl
        self._states: dict[str, _ExecutionState] = {}
        self._active_build_resolver: (
            Callable[[str, str], bool] | None
        ) = None
        self._lock = RLock()

    def bind_active_build_resolver(
        self,
        resolver: Callable[[str, str], bool],
    ) -> None:
        with self._lock:
            self._active_build_resolver = resolver

    def reserve(
        self,
        *,
        owner_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        roles: tuple[str, ...] = (),
    ) -> str:
        owner = _required_text(owner_id, "owner_id")
        execution_id = secrets.token_urlsafe(24)
        expires_at = int(
            (datetime.now(UTC) + self._ttl).timestamp()
        )
        with self._lock:
            self._states[execution_id] = _ExecutionState(
                owner_id=owner,
                tenant_id=_optional_text(tenant_id),
                workspace_id=_optional_text(workspace_id),
                roles=tuple(
                    str(role).strip().lower()
                    for role in roles
                    if str(role).strip()
                ),
                expires_at=expires_at,
            )
        return self._encode_token(execution_id, expires_at)

    def bind(
        self,
        token: str,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        execution_id, _ = self._verify_token(token)
        normalized_session_id = _required_text(
            session_id,
            "session_id",
        )
        normalized_turn_id = _required_text(turn_id, "turn_id")
        with self._lock:
            state = self._states.get(execution_id)
            if state is None:
                raise ReportToolTokenError(
                    "report_tool_execution_not_found"
                )
            state.session_id = normalized_session_id
            state.turn_id = normalized_turn_id
            owner_id = state.owner_id
            active_build_resolver = self._active_build_resolver
        if (
            active_build_resolver is not None
            and active_build_resolver(
                owner_id,
                normalized_session_id,
            )
        ):
            with self._lock:
                state = self._active_state(execution_id)
                if state is not None:
                    state.report_started = True
                    state.report_published = False

    def resolve(self, token: str) -> ReportBuildContext:
        execution_id, _ = self._verify_token(token)
        with self._lock:
            state = self._states.get(execution_id)
            if state is None:
                raise ReportToolTokenError(
                    "report_tool_execution_not_found"
                )
            if not state.session_id or not state.turn_id:
                raise ReportToolTokenError(
                    "report_tool_execution_unbound"
                )
            return ReportBuildContext(
                owner_id=state.owner_id,
                session_id=state.session_id,
                turn_id=state.turn_id,
                tenant_id=state.tenant_id,
                workspace_id=state.workspace_id,
                roles=state.roles,
            )

    def execution_id(self, token: str) -> str:
        execution_id, _ = self._verify_token(token)
        with self._lock:
            if execution_id not in self._states:
                raise ReportToolTokenError(
                    "report_tool_execution_not_found"
                )
        return execution_id

    def begin_model_round(self, execution_id: str) -> bool:
        normalized_id = _required_text(
            execution_id,
            "execution_id",
        )
        with self._lock:
            state = self._active_state(normalized_id)
            if state is None:
                return False
            if not state.report_started:
                return True
            if state.no_progress_rounds >= 3:
                return False
            state.no_progress_rounds += 1
            return True

    def record_successful_report_mutation(
        self,
        token: str,
        tool_name: str,
    ) -> None:
        self.record_report_mutation_result(
            token,
            tool_name,
            retryable=True,
            failed=False,
        )

    def record_report_mutation_result(
        self,
        token: str,
        tool_name: str,
        *,
        retryable: bool,
        failed: bool,
    ) -> None:
        execution_id, _ = self._verify_token(token)
        normalized_tool = _required_text(tool_name, "tool_name")
        if normalized_tool not in REPORT_BUILD_TOOL_NAMES:
            raise ReportToolTokenError(
                "unknown_report_build_tool"
            )
        with self._lock:
            state = self._active_state(execution_id)
            if state is None:
                raise ReportToolTokenError(
                    "report_tool_execution_not_found"
                )
            if normalized_tool == "get_report_build":
                if state.correction_read_available:
                    state.no_progress_rounds = 0
                    state.correction_read_available = False
                return
            if normalized_tool == "start_report_build" and not failed:
                state.report_started = True
                state.report_published = False
            elif normalized_tool != "get_report_build":
                state.report_started = True
            if normalized_tool == "publish_report_build" and not failed:
                state.report_published = True
            if not retryable:
                state.no_progress_rounds = 3
                state.correction_read_available = False
            elif failed:
                state.no_progress_rounds = 0
                state.correction_read_available = True
            else:
                state.no_progress_rounds = 0
                state.correction_read_available = False

    def no_progress_exhausted(self, execution_id: str) -> bool:
        normalized_id = _required_text(
            execution_id,
            "execution_id",
        )
        with self._lock:
            state = self._active_state(normalized_id)
            return bool(
                state
                and state.report_started
                and state.no_progress_rounds >= 3
            )

    def has_incomplete_report_build(self, execution_id: str) -> bool:
        normalized_id = _required_text(
            execution_id,
            "execution_id",
        )
        with self._lock:
            state = self._active_state(normalized_id)
            return bool(
                state
                and state.report_started
                and not state.report_published
            )

    def release(self, token: str) -> None:
        execution_id, _ = self._verify_token(token)
        with self._lock:
            self._states.pop(execution_id, None)

    def _active_state(
        self,
        execution_id: str,
    ) -> _ExecutionState | None:
        state = self._states.get(execution_id)
        if state is None:
            return None
        if state.expires_at < int(datetime.now(UTC).timestamp()):
            self._states.pop(execution_id, None)
            return None
        return state

    def _encode_token(
        self,
        execution_id: str,
        expires_at: int,
    ) -> str:
        payload = json.dumps(
            {
                "executionId": execution_id,
                "expiresAt": expires_at,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = _base64url(payload)
        signature = _base64url(
            hmac.new(
                self._secret,
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"{encoded}.{signature}"

    def _verify_token(self, token: str) -> tuple[str, int]:
        try:
            encoded, supplied_signature = str(token).split(".", 1)
            expected_signature = _base64url(
                hmac.new(
                    self._secret,
                    encoded.encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if not hmac.compare_digest(
                supplied_signature,
                expected_signature,
            ):
                raise ReportToolTokenError(
                    "invalid_report_tool_token"
                )
            payload = json.loads(
                _base64url_decode(encoded).decode("utf-8")
            )
            if set(payload) != {"executionId", "expiresAt"}:
                raise ReportToolTokenError(
                    "invalid_report_tool_token"
                )
            execution_id = _required_text(
                payload.get("executionId"),
                "execution_id",
            )
            expires_at = int(payload.get("expiresAt"))
        except ReportToolTokenError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReportToolTokenError(
                "invalid_report_tool_token"
            ) from exc
        if expires_at < int(datetime.now(UTC).timestamp()):
            with self._lock:
                self._states.pop(execution_id, None)
            raise ReportToolTokenError("report_tool_token_expired")
        return execution_id, expires_at


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _required_text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReportToolTokenError(f"{name}_required")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
