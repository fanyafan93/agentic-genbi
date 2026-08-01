"use client";

import { useState } from "react";
import type { FineReportCell, FineReportSheet } from "../api/finereport-reports";

function cellText(cell: FineReportCell): string {
  if (cell.value !== undefined && cell.value !== null && String(cell.value) !== "") return String(cell.value);
  if (cell.formula) return cell.formula;
  if (cell.binding?.dataset || cell.binding?.field) {
    return [cell.binding.dataset, cell.binding.field].filter(Boolean).join(".");
  }
  return "";
}

export function FineReportSheetGrid({ sheet, zoom }: { sheet: FineReportSheet; zoom: number }) {
  const [selectedCell, setSelectedCell] = useState<FineReportCell | null>(null);
  const columnWidth = Math.round(96 * zoom / 100);
  const rowHeight = Math.round(30 * zoom / 100);

  return (
    <div className="finereport-sheet-preview">
      {selectedCell && (
        <div className="finereport-cell-inspector" aria-live="polite">
          <strong>{selectedCell.cell}</strong>
          <span>{cellText(selectedCell) || "空单元格"}</span>
          {selectedCell.binding && (
            <code>{[selectedCell.binding.dataset, selectedCell.binding.field].filter(Boolean).join(".")}</code>
          )}
        </div>
      )}
      <div className="finereport-grid-scroll">
        <div
          className="finereport-grid"
          style={{
            gridTemplateColumns: `repeat(${sheet.columnCount}, ${columnWidth}px)`,
            gridTemplateRows: `repeat(${sheet.rowCount}, ${rowHeight}px)`,
          }}
        >
          {sheet.cells.map((cell) => {
            const text = cellText(cell);
            return (
              <button
                key={`${sheet.name}-${cell.cell}`}
                type="button"
                className={`finereport-grid-cell ${cell.formula ? "has-formula" : ""} ${cell.binding ? "has-binding" : ""}`}
                aria-label={`${cell.cell} ${text || "空单元格"}`}
                title={[cell.cell, cell.formula, cell.binding ? `${cell.binding.dataset}.${cell.binding.field}` : ""].filter(Boolean).join(" · ")}
                style={{
                  gridColumn: `${cell.columnIndex} / span ${cell.colspan}`,
                  gridRow: `${cell.row} / span ${cell.rowspan}`,
                }}
                onClick={() => setSelectedCell(cell)}
              >
                {text}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
