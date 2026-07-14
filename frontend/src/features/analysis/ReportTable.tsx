import type { ReportTable as ReportTableData } from "../../types/analysis";

export function ReportTable({ table }: { table: ReportTableData }) {
  return (
    <div className="table-shell">
      <table>
        <thead>
          <tr>{table.columns.map((column) => <th key={column.name}>{column.name}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {table.columns.map((column) => <td key={column.name}>{formatCell(row[column.name])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="table-meta">{table.row_count} 行{table.truncated ? " · 已截断" : ""}</p>
    </div>
  );
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

