from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.reports.build_models import (
    ReportBuildRecord,
    ReportValidationIssue,
    report_build_to_payload,
)
from backend.reports.build_store import ReportBuildStore
from backend.reports.models import report_to_payload
from backend.reports.schema import (
    ReportValidationError,
    collect_report_validation_errors,
)


REPORT_BUILD_TOOL_NAMES = (
    "start_report_build",
    "get_report_build",
    "set_report_filters",
    "upsert_report_query",
    "upsert_report_chart",
    "upsert_report_table",
    "set_report_layout",
    "validate_report_build",
    "publish_report_build",
)


@dataclass(frozen=True)
class ReportBuildContext:
    owner_id: str
    session_id: str
    turn_id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    roles: tuple[str, ...] = ()


class ReportBuildNotFound(LookupError):
    pass


class ReportBuildAccessDenied(PermissionError):
    pass


class ReportBuildValidationFailed(ValueError):
    pass


class ReportBuildRetryExhausted(ValueError):
    pass


class ReportBuildService:
    def __init__(self, store: ReportBuildStore) -> None:
        self.store = store

    def record_argument_validation_failure(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ReportBuildContext,
        errors: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        targets = {
            "set_report_filters": (
                "set_report_filters:filters",
                "filters",
            ),
            "upsert_report_query": (
                "upsert_report_query:"
                f"{str(arguments.get('query_id') or '<empty>').strip()}",
                "queries",
            ),
            "upsert_report_chart": (
                "upsert_report_chart:"
                f"{str(arguments.get('chart_id') or '<empty>').strip()}",
                "charts",
            ),
            "upsert_report_table": (
                "upsert_report_table:"
                f"{str(arguments.get('table_id') or '<empty>').strip()}",
                "tables",
            ),
            "set_report_layout": (
                "set_report_layout:layout",
                "layout",
            ),
        }
        target = targets.get(tool_name)
        if target is None:
            return None
        record, access_error = self._authorised_build(
            arguments,
            context,
        )
        if access_error or record is None:
            return None
        issues = [
            ReportValidationIssue(
                path=".".join(
                    str(part)
                    for part in error.get("loc", ())
                )
                or tool_name,
                code=str(
                    error.get("type")
                    or "invalid_report_build_arguments"
                ),
                message=str(
                    error.get("msg")
                    or "Report build tool arguments are invalid."
                ),
            )
            for error in errors
        ]
        if not issues:
            issues = [
                ReportValidationIssue(
                    path=tool_name,
                    code="invalid_report_build_arguments",
                    message=(
                        "Report build tool arguments are invalid."
                    ),
                )
            ]
        step_key, changed_section = target
        return self._persist_failure(
            record,
            context,
            step_key=step_key,
            issues=issues,
            changed_section=changed_section,
        )

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        handlers = {
            "start_report_build": self._start,
            "get_report_build": self._get,
            "set_report_filters": self._set_filters,
            "upsert_report_query": self._upsert_query,
            "upsert_report_chart": self._upsert_chart,
            "upsert_report_table": self._upsert_table,
            "set_report_layout": self._set_layout,
            "validate_report_build": self._validate,
            "publish_report_build": self._publish,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            raise ValueError("unknown_report_build_tool")
        return handler(arguments, context)

    def _start(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        title = _required_text(arguments.get("title"), "title")
        subtitle = _required_text(arguments.get("subtitle"), "subtitle")
        active = self.store.get_active_for_session(
            context.session_id,
            owner_id=context.owner_id,
        )
        if (
            active is not None
            and active.turnId == context.turn_id
            and active.content.get("title") == title
        ):
            return _success_payload(
                active,
                action="build_started",
                changed_section="metadata",
            )

        now = datetime.now(UTC)
        record = ReportBuildRecord(
            id=f"build_{uuid4().hex}",
            ownerId=_required_text(context.owner_id, "owner_id"),
            sessionId=_required_text(context.session_id, "session_id"),
            turnId=_required_text(context.turn_id, "turn_id"),
            targetReportId=None,
            status="building",
            content={
                "title": title,
                "subtitle": subtitle,
                "layout": {"content": [], "zones": {}},
                "filters": {},
                "queries": {},
                "charts": {},
                "tables": {},
            },
            validationErrors=[],
            revision=0,
            publishedReportId=None,
            lastSuccessfulStep="start_report_build",
            stepAttempts={},
            createdAt=now.isoformat(),
            updatedAt=now.isoformat(),
            expiresAt=(now + timedelta(days=7)).isoformat(),
        )
        created = self.store.create_build(record)
        return _success_payload(
            created,
            action="build_started",
            changed_section="metadata",
        )

    def _get(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        record, error = self._authorised_build(arguments, context)
        if error:
            return error
        assert record is not None
        return {
            "ok": True,
            "action": "build_read",
            "buildId": record.id,
            "revision": record.revision,
            "status": record.status,
            "build": report_build_to_payload(record),
        }

    def _set_filters(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        filters = arguments.get("filters")
        if not isinstance(filters, dict):
            return self._argument_error(
                arguments,
                context,
                step_key="set_report_filters:filters",
                path="filters",
                message="filters must be an object.",
            )
        return self._mutate_section(
            arguments,
            context,
            step_name="set_report_filters",
            step_key="set_report_filters:filters",
            changed_section="filters",
            mutate=lambda content: {
                **content,
                "filters": deepcopy(filters),
            },
        )

    def _upsert_query(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        return self._upsert_definition(
            arguments,
            context,
            step_name="upsert_report_query",
            section="queries",
            identifier_key="query_id",
            value_key="query",
        )

    def _upsert_chart(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        return self._upsert_definition(
            arguments,
            context,
            step_name="upsert_report_chart",
            section="charts",
            identifier_key="chart_id",
            value_key="chart",
        )

    def _upsert_table(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        return self._upsert_definition(
            arguments,
            context,
            step_name="upsert_report_table",
            section="tables",
            identifier_key="table_id",
            value_key="table",
        )

    def _set_layout(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        layout = arguments.get("layout")
        if not isinstance(layout, dict):
            return self._argument_error(
                arguments,
                context,
                step_key="set_report_layout:layout",
                path="layout",
                message="layout must be an object.",
            )
        return self._mutate_section(
            arguments,
            context,
            step_name="set_report_layout",
            step_key="set_report_layout:layout",
            changed_section="layout",
            mutate=lambda content: {
                **content,
                "layout": deepcopy(layout),
            },
        )

    def _validate(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        record, error = self._authorised_build(arguments, context)
        if error:
            return error
        assert record is not None
        issues = collect_report_validation_errors(record.content)
        if issues:
            return self._persist_failure(
                record,
                context,
                step_key="validate_report_build:all",
                issues=issues,
                changed_section="validation",
            )
        updated = self.store.mutate_build(
            record.id,
            owner_id=context.owner_id,
            mutation=lambda current: _successful_record(
                current,
                content=current.content,
                step_name="validate_report_build",
                step_key="validate_report_build:all",
            ),
        )
        if updated is None:
            return _not_found_payload(record.id)
        return _success_payload(
            updated,
            action="build_validated",
            changed_section="validation",
        )

    def _publish(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> dict[str, Any]:
        record, error = self._authorised_build(arguments, context)
        if error:
            return error
        assert record is not None
        if record.publishedReportId:
            published = self.store.publish_build(
                record.id,
                owner_id=context.owner_id,
                turn_id=context.turn_id,
            )
            return _published_payload(published)

        issues = collect_report_validation_errors(record.content)
        if issues:
            return self._persist_failure(
                record,
                context,
                step_key="publish_report_build:all",
                issues=issues,
                changed_section="validation",
            )
        try:
            published = self.store.publish_build(
                record.id,
                owner_id=context.owner_id,
                turn_id=context.turn_id,
            )
        except ReportValidationError as exc:
            return self._persist_failure(
                record,
                context,
                step_key="publish_report_build:all",
                issues=[
                    ReportValidationIssue(
                        path=exc.path,
                        code="invalid_value",
                        message=exc.message,
                    )
                ],
                changed_section="validation",
            )
        return _published_payload(published)

    def _upsert_definition(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
        *,
        step_name: str,
        section: str,
        identifier_key: str,
        value_key: str,
    ) -> dict[str, Any]:
        identifier = str(arguments.get(identifier_key) or "").strip()
        value = arguments.get(value_key)
        if not identifier:
            return self._argument_error(
                arguments,
                context,
                step_key=f"{step_name}:<empty>",
                path=identifier_key,
                message=f"{identifier_key} is required.",
            )
        if not isinstance(value, dict):
            return self._argument_error(
                arguments,
                context,
                step_key=f"{step_name}:{identifier}",
                path=f"{section}.{identifier}",
                message=f"{value_key} must be an object.",
            )

        def mutate(content: dict[str, Any]) -> dict[str, Any]:
            definitions = deepcopy(content.get(section, {}))
            definitions[identifier] = deepcopy(value)
            return {**content, section: definitions}

        return self._mutate_section(
            arguments,
            context,
            step_name=step_name,
            step_key=f"{step_name}:{identifier}",
            changed_section=section,
            mutate=mutate,
        )

    def _mutate_section(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
        *,
        step_name: str,
        step_key: str,
        changed_section: str,
        mutate: Any,
    ) -> dict[str, Any]:
        record, error = self._authorised_build(arguments, context)
        if error:
            return error
        assert record is not None
        if record.status == "published":
            return _error_payload(
                "report_build_published",
                "Published Report builds cannot be changed.",
                build_id=record.id,
            )
        candidate = mutate(deepcopy(record.content))
        issues = collect_report_validation_errors(candidate)
        if issues:
            return self._persist_failure(
                record,
                context,
                step_key=step_key,
                issues=issues,
                changed_section=changed_section,
            )
        updated = self.store.mutate_build(
            record.id,
            owner_id=context.owner_id,
            mutation=lambda current: _successful_record(
                current,
                content=candidate,
                step_name=step_name,
                step_key=step_key,
            ),
        )
        if updated is None:
            return _not_found_payload(record.id)
        return _success_payload(
            updated,
            action="build_updated",
            changed_section=changed_section,
        )

    def _argument_error(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
        *,
        step_key: str,
        path: str,
        message: str,
    ) -> dict[str, Any]:
        record, error = self._authorised_build(arguments, context)
        if error:
            return error
        assert record is not None
        return self._persist_failure(
            record,
            context,
            step_key=step_key,
            issues=[
                ReportValidationIssue(
                    path=path,
                    code="invalid_type",
                    message=message,
                )
            ],
            changed_section=path.split(".", 1)[0],
        )

    def _persist_failure(
        self,
        record: ReportBuildRecord,
        context: ReportBuildContext,
        *,
        step_key: str,
        issues: list[ReportValidationIssue],
        changed_section: str,
    ) -> dict[str, Any]:
        updated = self.store.mutate_build(
            record.id,
            owner_id=context.owner_id,
            mutation=lambda current: _failed_record(
                current,
                step_key=step_key,
                issues=issues,
            ),
        )
        if updated is None:
            return _not_found_payload(record.id)
        attempts = updated.stepAttempts.get(step_key, 0)
        retryable = attempts < 3
        payload = {
            "ok": False,
            "action": "build_failed",
            "buildId": updated.id,
            "revision": updated.revision,
            "status": updated.status,
            "changedSection": changed_section,
            "retryable": retryable,
            "errors": deepcopy(updated.validationErrors),
            "build": report_build_to_payload(updated),
        }
        if retryable:
            payload["error"] = {
                "code": "report_build_validation_failed",
                "message": "The Report build step failed validation.",
            }
        else:
            payload["error"] = {
                "code": "report_build_retry_exhausted",
                "message": "The Report build step exhausted correction retries.",
            }
        return payload

    def _authorised_build(
        self,
        arguments: dict[str, Any],
        context: ReportBuildContext,
    ) -> tuple[
        ReportBuildRecord | None,
        dict[str, Any] | None,
    ]:
        build_id = str(arguments.get("build_id") or "").strip()
        if not build_id:
            return None, _error_payload(
                "invalid_report_build_arguments",
                "build_id is required.",
            )
        record = self.store.get_build(build_id)
        if record is None:
            return None, _not_found_payload(build_id)
        if (
            record.sessionId != context.session_id
            or (
                record.ownerId != context.owner_id
                and "admin" not in context.roles
            )
        ):
            return None, _error_payload(
                "report_build_access_denied",
                "The Report build is outside the current analysis context.",
                build_id=build_id,
            )
        return record, None


def _successful_record(
    current: ReportBuildRecord,
    *,
    content: dict[str, Any],
    step_name: str,
    step_key: str,
) -> ReportBuildRecord:
    attempts = dict(current.stepAttempts)
    attempts.pop(step_key, None)
    return replace(
        current,
        status="building",
        content=deepcopy(content),
        validationErrors=[],
        revision=current.revision + 1,
        lastSuccessfulStep=step_name,
        stepAttempts=attempts,
        updatedAt=datetime.now(UTC).isoformat(),
    )


def _failed_record(
    current: ReportBuildRecord,
    *,
    step_key: str,
    issues: list[ReportValidationIssue],
) -> ReportBuildRecord:
    attempts = dict(current.stepAttempts)
    attempts[step_key] = attempts.get(step_key, 0) + 1
    return replace(
        current,
        status="failed",
        validationErrors=[asdict(issue) for issue in issues],
        revision=current.revision + 1,
        stepAttempts=attempts,
        updatedAt=datetime.now(UTC).isoformat(),
    )


def _success_payload(
    record: ReportBuildRecord,
    *,
    action: str,
    changed_section: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "action": action,
        "buildId": record.id,
        "revision": record.revision,
        "status": record.status,
        "changedSection": changed_section,
        "build": report_build_to_payload(record),
    }


def _published_payload(
    published: tuple[ReportBuildRecord, Any] | None,
) -> dict[str, Any]:
    if published is None:
        return _error_payload(
            "report_build_not_found",
            "The Report build was not found.",
        )
    build, report = published
    return {
        "ok": True,
        "action": "build_published",
        "buildId": build.id,
        "revision": build.revision,
        "status": build.status,
        "changedSection": "publication",
        "build": report_build_to_payload(build),
        "report": report_to_payload(
            report,
            source_session_id=build.sessionId,
        ),
    }


def _not_found_payload(build_id: str) -> dict[str, Any]:
    return _error_payload(
        "report_build_not_found",
        "The Report build was not found.",
        build_id=build_id,
    )


def _error_payload(
    code: str,
    message: str,
    *,
    build_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if build_id:
        payload["buildId"] = build_id
    return payload


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required.")
    return text
