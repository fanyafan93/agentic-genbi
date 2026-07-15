import type { AnalysisReport } from "../../types/analysis";

export interface ChartOption {
  title: { text: string };
  xAxis: { type: "category"; data: string[] };
  yAxis: { type: "value" };
  series: Array<{ name: string; type: "line" | "bar"; data: number[] }>;
}

export function buildChartOption(report: AnalysisReport): ChartOption | null {
  if (!report.chart) return null;
  const { chart, table } = report;
  return {
    title: { text: chart.title },
    xAxis: { type: "category", data: table.rows.map((row) => String(row[chart.x_field] ?? "-")) },
    yAxis: { type: "value" },
    series: chart.y_fields.map((field) => ({
      name: field,
      type: chart.type === "pie" ? "bar" : chart.type,
      data: table.rows.map((row) => Number(row[field] ?? 0)),
    })),
  };
}

export function ReportChart({ report }: { report: AnalysisReport }) {
  const option = buildChartOption(report);
  if (!option) return null;

  return (
    <section className="chart-panel" aria-label={option.title.text}>
      <div className="chart-heading"><span>VISUAL READ</span><h3>{option.title.text}</h3></div>
      <div className="chart-bars">
        {option.xAxis.data.map((label, index) => (
          <div className="bar-column" key={`${label}-${index}`}>
            <div className="bar" style={{ height: `${Math.min(100, Math.max(8, option.series[0]?.data[index] ?? 0))}%` }} />
            <span>{label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

