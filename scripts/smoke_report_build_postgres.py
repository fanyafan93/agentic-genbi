from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.persistence.postgres_stores import (
    PostgresCodexProjectionBackend,
    PostgresReportBuildStore,
    PostgresReportStore,
    PostgresSessionCatalogBackend,
    get_postgres_database_url,
)
from backend.harness.codex_projection_store import TurnRecord
from backend.reports.build_models import ReportBuildRecord


def main() -> int:
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError(
            "GENBI_DATABASE_URL or AUTH_DATABASE_URL is required."
        )
    suffix = uuid4().hex[:10]
    prefix = f"smoke_report_build_{suffix}"
    session_ids = [f"{prefix}_session_a", f"{prefix}_session_b"]
    turn_ids = [f"{prefix}_turn_a", f"{prefix}_turn_b"]
    build_ids = [f"{prefix}_build_a", f"{prefix}_build_b"]
    report_ids: list[str] = []

    PostgresSessionCatalogBackend(database_url)
    turn_backend = PostgresCodexProjectionBackend(database_url)
    PostgresReportStore(database_url)
    store = PostgresReportBuildStore(database_url)

    try:
        _insert_fixtures(
            database_url,
            session_ids,
            turn_ids,
            turn_backend=turn_backend,
        )
        for index in range(2):
            store.create_build(
                _build_record(
                    build_id=build_ids[index],
                    session_id=session_ids[index],
                    turn_id=turn_ids[index],
                )
            )

        def mutate(index: int) -> ReportBuildRecord | None:
            return store.mutate_build(
                build_ids[index],
                owner_id="smoke-report-build-user",
                mutation=lambda current: replace(
                    current,
                    revision=current.revision + 1,
                    content={
                        **current.content,
                        "charts": {
                            f"chart-{index}": {
                                "queryId": f"query-{index}",
                                "option": {
                                    "series": [{"type": "bar"}],
                                },
                            }
                        },
                        "queries": {
                            f"query-{index}": {
                                "dataSource": "doris",
                                "sql": "SELECT 1 AS value",
                                "parameters": {},
                                "pagination": False,
                            }
                        },
                    },
                    updatedAt=datetime.now(UTC).isoformat(),
                ),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            mutations = list(executor.map(mutate, range(2)))
        if any(item is None for item in mutations):
            raise AssertionError("concurrent build mutation returned None")

        first = store.get_build(build_ids[0])
        second = store.get_build(build_ids[1])
        if first is None or second is None:
            raise AssertionError("concurrent builds were not persisted")
        if first.revision != 1 or second.revision != 1:
            raise AssertionError("concurrent build revisions were lost")
        if "chart-0" not in first.content["charts"]:
            raise AssertionError("first build content was overwritten")
        if "chart-1" not in second.content["charts"]:
            raise AssertionError("second build content was overwritten")

        published_once = store.publish_build(
            build_ids[0],
            owner_id="smoke-report-build-user",
            turn_id=turn_ids[0],
        )
        published_twice = store.publish_build(
            build_ids[0],
            owner_id="smoke-report-build-user",
            turn_id=turn_ids[0],
        )
        if published_once is None or published_twice is None:
            raise AssertionError("publish returned None")
        report_ids.append(published_once[1].id)
        if published_once[1].id != published_twice[1].id:
            raise AssertionError("repeated publish created another Report")
        if _count_reports(database_url, report_ids[0]) != 1:
            raise AssertionError("publish did not create exactly one Report")

        print("report build postgres smoke: PASS")
        return 0
    finally:
        _cleanup(
            database_url,
            build_ids=build_ids,
            report_ids=report_ids,
            turn_ids=turn_ids,
            session_ids=session_ids,
        )


def _build_record(
    *,
    build_id: str,
    session_id: str,
    turn_id: str,
) -> ReportBuildRecord:
    now = datetime.now(UTC)
    return ReportBuildRecord(
        id=build_id,
        ownerId="smoke-report-build-user",
        sessionId=session_id,
        turnId=turn_id,
        targetReportId=None,
        status="building",
        content={
            "title": f"Smoke {build_id}",
            "subtitle": "PostgreSQL concurrency",
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


def _insert_fixtures(
    database_url: str,
    session_ids: list[str],
    turn_ids: list[str],
    *,
    turn_backend: PostgresCodexProjectionBackend,
) -> None:
    import psycopg

    now = datetime.now(UTC)
    with psycopg.connect(database_url, autocommit=True) as conn:
        for session_id in session_ids:
            conn.execute(
                """
                INSERT INTO analysis_threads (
                    id, product_kind, title, tenant_id, user_id,
                    workspace_id, status, created_at, updated_at, metadata
                ) VALUES (
                    %s, 'analysis', 'ReportBuild smoke', 'smoke-tenant',
                    'smoke-report-build-user', 'smoke-workspace',
                    'active', %s, %s, '{}'::jsonb
                )
                ON CONFLICT (id) DO NOTHING
                """,
                (session_id, now, now),
            )
    for session_id, turn_id in zip(
        session_ids,
        turn_ids,
        strict=True,
    ):
        turn_backend.upsert_turn(
            TurnRecord(
                id=turn_id,
                sessionId=session_id,
                inputKind="start",
                question="smoke",
                inputText="smoke",
                status="completed",
                createdAt=now.isoformat(),
                updatedAt=now.isoformat(),
                startedAt=now.isoformat(),
                completedAt=now.isoformat(),
                metadata={},
                codexSessionId=None,
                codexTurnId=None,
            )
        )


def _count_reports(database_url: str, report_id: str) -> int:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT count(*) FROM reports WHERE id = %s",
            (report_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def _cleanup(
    database_url: str,
    *,
    build_ids: list[str],
    report_ids: list[str],
    turn_ids: list[str],
    session_ids: list[str],
) -> None:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM report_builds WHERE id = ANY(%s)",
            (build_ids,),
        )
        if report_ids:
            conn.execute(
                "DELETE FROM reports WHERE id = ANY(%s)",
                (report_ids,),
            )
        conn.execute(
            "DELETE FROM analysis_turns WHERE id = ANY(%s)",
            (turn_ids,),
        )
        conn.execute(
            "DELETE FROM analysis_threads WHERE id = ANY(%s)",
            (session_ids,),
        )


if __name__ == "__main__":
    raise SystemExit(main())
