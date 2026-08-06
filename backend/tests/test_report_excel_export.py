from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from backend.reports.excel_export import _write_workbook


def test_excel_export_keeps_text_literal_and_tolerates_empty_numbers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.xlsx"

    _write_workbook(
        path,
        [
            {"field": "order_id", "title": "订单号", "type": "text"},
            {"field": "amount", "title": "金额", "type": "number"},
        ],
        [{"order_id": "=2+2", "amount": ""}],
    )

    with ZipFile(path) as workbook:
        worksheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "=2+2" in worksheet
    assert "<f>" not in worksheet
