from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.reports.build_context import (
    ReportToolExecutionRegistry,
    ReportToolTokenError,
)


def _token_payload(token: str) -> dict[str, object]:
    encoded_payload = token.split(".", 1)[0]
    padding = "=" * (-len(encoded_payload) % 4)
    return json.loads(
        base64.urlsafe_b64decode(
            encoded_payload + padding
        ).decode("utf-8")
    )


def test_execution_token_contains_only_opaque_id_and_expiry() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")

    token = registry.reserve(
        owner_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        roles=("analyst",),
    )

    assert set(_token_payload(token)) == {"executionId", "expiresAt"}
    assert "user-1" not in token
    assert "tenant-1" not in token
    assert "workspace-1" not in token


def test_execution_token_resolves_only_after_server_ids_are_bound() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    token = registry.reserve(
        owner_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        roles=("analyst",),
    )

    with pytest.raises(ReportToolTokenError):
        registry.resolve(token)

    registry.bind(
        token,
        session_id="session-1",
        turn_id="turn-1",
    )
    context = registry.resolve(token)

    assert context.owner_id == "user-1"
    assert context.session_id == "session-1"
    assert context.turn_id == "turn-1"
    assert context.tenant_id == "tenant-1"
    assert context.workspace_id == "workspace-1"
    assert context.roles == ("analyst",)


def test_released_execution_token_cannot_be_reused() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    token = registry.reserve(owner_id="user-1")
    registry.bind(token, session_id="session-1", turn_id="turn-1")

    registry.release(token)

    with pytest.raises(ReportToolTokenError):
        registry.resolve(token)


def test_report_build_allows_three_no_progress_rounds_then_blocks() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    token = registry.reserve(owner_id="user-1")
    execution_id = registry.execution_id(token)

    assert registry.begin_model_round(execution_id) is True
    registry.record_successful_report_mutation(
        token,
        "start_report_build",
    )

    assert registry.begin_model_round(execution_id) is True
    assert registry.begin_model_round(execution_id) is True
    assert registry.begin_model_round(execution_id) is True
    assert registry.no_progress_exhausted(execution_id) is True
    assert registry.begin_model_round(execution_id) is False


def test_successful_mutation_resets_no_progress_but_read_does_not() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    token = registry.reserve(owner_id="user-1")
    execution_id = registry.execution_id(token)
    registry.record_successful_report_mutation(
        token,
        "start_report_build",
    )

    assert registry.begin_model_round(execution_id) is True
    assert registry.begin_model_round(execution_id) is True
    registry.record_successful_report_mutation(
        token,
        "get_report_build",
    )
    assert registry.begin_model_round(execution_id) is True
    assert registry.begin_model_round(execution_id) is False

    registry.record_successful_report_mutation(
        token,
        "upsert_report_query",
    )
    assert registry.no_progress_exhausted(execution_id) is False
    assert registry.begin_model_round(execution_id) is True


def test_one_failed_build_read_opens_correction_window_only_once() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    token = registry.reserve(owner_id="user-1")
    execution_id = registry.execution_id(token)
    registry.record_successful_report_mutation(
        token,
        "start_report_build",
    )
    registry.record_report_mutation_result(
        token,
        "upsert_report_query",
        retryable=True,
        failed=True,
    )

    assert registry.begin_model_round(execution_id) is True
    assert registry.begin_model_round(execution_id) is True
    registry.record_report_mutation_result(
        token,
        "get_report_build",
        retryable=True,
        failed=False,
    )

    assert registry.begin_model_round(execution_id) is True
    registry.record_report_mutation_result(
        token,
        "get_report_build",
        retryable=True,
        failed=False,
    )
    assert registry.begin_model_round(execution_id) is True
    assert registry.begin_model_round(execution_id) is True
    assert registry.begin_model_round(execution_id) is False


def test_started_build_is_incomplete_until_publish_succeeds() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    token = registry.reserve(owner_id="user-1")
    execution_id = registry.execution_id(token)

    assert registry.has_incomplete_report_build(execution_id) is False

    registry.record_successful_report_mutation(
        token,
        "start_report_build",
    )
    assert registry.has_incomplete_report_build(execution_id) is True

    registry.record_successful_report_mutation(
        token,
        "upsert_report_query",
    )
    assert registry.has_incomplete_report_build(execution_id) is True

    registry.record_successful_report_mutation(
        token,
        "publish_report_build",
    )
    assert registry.has_incomplete_report_build(execution_id) is False


def test_binding_marks_existing_session_build_as_incomplete() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    registry.bind_active_build_resolver(
        lambda owner_id, session_id: (
            owner_id == "user-1" and session_id == "session-1"
        )
    )
    token = registry.reserve(owner_id="user-1")
    execution_id = registry.execution_id(token)

    registry.bind(
        token,
        session_id="session-1",
        turn_id="turn-2",
    )

    assert registry.has_incomplete_report_build(execution_id) is True
