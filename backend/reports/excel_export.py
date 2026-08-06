from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import xlsxwriter

from backend.reports.query_service import ReportQueryService


class ReportTableNotExportable(LookupError):
    pass


@dataclass(frozen=True)
class ReportExcelExport:
    path: Path
    filename: str
    row_count: int


def create_report_excel_export(
    report: Any,
    table_id: str,
    query_service: ReportQueryService,
    *,
    filters: Mapping[str, Any],
    sort: Mapping[str, Any] | None = None,
    column_filters: Mapping[str, Any] | None = None,
) -> ReportExcelExport:
    table = report.tables.get(table_id)
    if not isinstance(table, dict) or table.get("type", "list") != "list":
        raise ReportTableNotExportable(table_id)
    columns = table.get("exportColumns")
    if not isinstance(columns, list) or not columns:
        raise ReportTableNotExportable(table_id)
    max_rows = int(os.getenv("GENBI_REPORT_EXPORT_MAX_ROWS", "100000"))
    rows = query_service.execute_export(
        report,
        str(table.get("queryId") or ""),
        filters=filters,
        fields=[str(column["field"]) for column in columns],
        max_rows=max_rows,
        sort=sort,
        column_filters=column_filters,
    )
    descriptor, raw_path = tempfile.mkstemp(
        prefix="genbi-report-",
        suffix=".xlsx",
    )
    os.close(descriptor)
    path = Path(raw_path)
    try:
        _write_workbook(path, columns, rows)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return ReportExcelExport(
        path=path,
        filename=_export_filename(report.title, table_id),
        row_count=len(rows),
    )


def remove_export_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def _write_workbook(
    path: Path,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    workbook = xlsxwriter.Workbook(
        str(path),
        {"constant_memory": True},
    )
    try:
        worksheet = workbook.add_worksheet("明细")
        header_format = workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#1F4E78",
                "border": 1,
                "align": "center",
            }
        )
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
        datetime_format = workbook.add_format(
            {"num_format": "yyyy-mm-dd hh:mm:ss"}
        )
        for column_index, column in enumerate(columns):
            title = str(column["title"])
            worksheet.write_string(0, column_index, title, header_format)
            worksheet.set_column(
                column_index,
                column_index,
                min(40, max(12, len(title) + 4)),
            )
        for row_index, row in enumerate(rows, start=1):
            for column_index, column in enumerate(columns):
                _write_cell(
                    worksheet,
                    row_index,
                    column_index,
                    row.get(str(column["field"])),
                    str(column.get("type") or "text"),
                    date_format,
                    datetime_format,
                )
        worksheet.freeze_panes(1, 0)
        if columns:
            worksheet.autofilter(0, 0, len(rows), len(columns) - 1)
    finally:
        workbook.close()


def _write_cell(
    worksheet: Any,
    row: int,
    column: int,
    value: Any,
    value_type: str,
    date_format: Any,
    datetime_format: Any,
) -> None:
    if value is None:
        worksheet.write_blank(row, column, None)
        return
    if value_type == "number" and not isinstance(value, bool):
        try:
            worksheet.write_number(row, column, float(value))
            return
        except (TypeError, ValueError):
            if value == "":
                worksheet.write_blank(row, column, None)
                return
    if value_type == "boolean":
        worksheet.write_boolean(row, column, bool(value))
        return
    if value_type in {"date", "datetime"}:
        parsed = _as_datetime(value)
        if parsed is not None:
            worksheet.write_datetime(
                row,
                column,
                parsed,
                date_format if value_type == "date" else datetime_format,
            )
            return
    worksheet.write_string(row, column, str(value))


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _export_filename(title: str, table_id: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", f"{title}-{table_id}")
    return f"{base[:120] or 'report'}.xlsx"
