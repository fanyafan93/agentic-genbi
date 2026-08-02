from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.report_query_service import (
    CHANNEL_SALES_QUERY_REF,
    REGION_CHANNEL_SALES_QUERY_REF,
    ReportQueryFilterError,
    ReportQueryService,
)
from backend.resource_library.database_tools import DatabaseConfig, ReadonlyDatabaseTools


class _Cursor:
    description = [("channel",), ("salesAmount",), ("netRevenue",), ("refundAmount",)]

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return [
            {"channel": "线上自营", "salesAmount": 120.0, "netRevenue": 100.0, "refundAmount": 5.0},
            {"channel": "线下", "salesAmount": 80.0, "netRevenue": 70.0, "refundAmount": 2.0},
        ]

    def close(self) -> None:
        pass


class _Connection:
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def close(self) -> None:
        pass


class ReportQueryServiceTest(unittest.TestCase):
    def test_channel_sales_query_is_server_owned_and_binds_filters(self) -> None:
        connection = _Connection()
        service = ReportQueryService(
            ReadonlyDatabaseTools(DatabaseConfig(host="x", port=3306, user="u", password="p"), connection=connection)
        )

        result = service.run(CHANNEL_SALES_QUERY_REF, {"month": "2026-08", "brand": "花西子", "region": "华东"})

        sql, parameters = connection.cursor_instance.executed[0]
        self.assertIn("FROM dm.dm_fina_operation_mgmt_rpt", sql)
        self.assertIn("vbrand = %s", sql)
        self.assertIn("vregion = %s", sql)
        self.assertEqual(parameters, ("2026-08", "花西子", "华东"))
        self.assertAlmostEqual(result.rows[0]["salesShare"], 0.6)
        self.assertEqual(result.columns[-1], "salesShare")

    def test_channel_sales_query_rejects_unknown_and_invalid_filters(self) -> None:
        service = ReportQueryService(
            ReadonlyDatabaseTools(DatabaseConfig(host="x", port=3306, user="u", password="p"), connection=_Connection())
        )

        with self.assertRaises(ReportQueryFilterError):
            service.run(CHANNEL_SALES_QUERY_REF, {"month": "2026-08", "sort": "drop table"})
        with self.assertRaises(ReportQueryFilterError):
            service.run(CHANNEL_SALES_QUERY_REF, {"month": "August"})

    def test_region_channel_query_groups_region_and_channel(self) -> None:
        connection = _Connection()
        service = ReportQueryService(
            ReadonlyDatabaseTools(DatabaseConfig(host="x", port=3306, user="u", password="p"), connection=connection)
        )

        result = service.run(REGION_CHANNEL_SALES_QUERY_REF, {"month": "2026-08"})

        sql, parameters = connection.cursor_instance.executed[0]
        self.assertEqual(parameters, ("2026-08",))
        self.assertIn("COALESCE(NULLIF(vregion, ''), '未分类') AS region", sql)
        self.assertIn("GROUP BY COALESCE(NULLIF(vregion, ''), '未分类'), COALESCE(NULLIF(vchannel_type, ''), '未分类')", sql)
        self.assertEqual(result.queryRef, REGION_CHANNEL_SALES_QUERY_REF)

    def test_query_records_metadata_but_not_rows_in_audit_store(self) -> None:
        class AuditStore:
            def __init__(self) -> None:
                self.record: dict[str, object] | None = None

            def record_query(self, **kwargs: object) -> None:
                self.record = kwargs

        audit_store = AuditStore()
        service = ReportQueryService(
            ReadonlyDatabaseTools(DatabaseConfig(host="x", port=3306, user="u", password="p"), connection=_Connection()),
            audit_store=audit_store,
        )

        service.run(
            CHANNEL_SALES_QUERY_REF,
            {"month": "2026-08"},
            audit_context={"source": "codex_authorized_snapshot", "turn_id": "turn_1", "data_egress_authorized": True},
        )

        self.assertIsNotNone(audit_store.record)
        self.assertEqual(audit_store.record["query_ref"], CHANNEL_SALES_QUERY_REF)
        self.assertEqual(audit_store.record["context"], {"source": "codex_authorized_snapshot", "turn_id": "turn_1", "data_egress_authorized": True})
        self.assertNotIn("rows", audit_store.record)


if __name__ == "__main__":
    unittest.main()
