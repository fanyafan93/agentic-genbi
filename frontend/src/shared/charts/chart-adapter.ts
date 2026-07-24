import type { EChartsOption } from "echarts";
import type { AnalysisRow, ChartSpec } from "@/modules/analysis/types/analysis";

function formatValue(value: unknown, format?: string) {
  if (typeof value !== "number") return String(value ?? "");
  if (format === "currency") return `CNY ${value.toLocaleString("zh-CN")}`;
  if (format === "percent") return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString("zh-CN");
}

export function toEChartsOption(spec: ChartSpec, rows: AnalysisRow[]): EChartsOption {
  const categories = rows.map((row) => String(row[spec.categoryField] ?? ""));
  const series: EChartsOption["series"] = spec.series.map((item) => ({
    name: item.name,
    type: spec.type === "line" ? "line" : "bar",
    data: rows.map((row) => row[item.field] as number),
    barMaxWidth: 40,
    itemStyle: { borderRadius: [4, 4, 0, 0] },
  }));

  return {
    color: ["#1e3a5f", "#e8685a", "#6b8f89"],
    title: { text: spec.title, left: 0, top: 0, textStyle: { fontSize: 13, fontWeight: 700, color: "#1a1a1a" } },
    grid: { left: 42, right: 16, top: 44, bottom: 36 },
    tooltip: {
      trigger: "axis",
      formatter(params) {
        const first = Array.isArray(params) ? params[0] : params;
        const dataIndex = first?.dataIndex ?? 0;
        const lines = spec.series.map((item) => `${item.name}: ${formatValue(rows[dataIndex]?.[item.field], item.format)}`);
        return [categories[dataIndex], ...lines].join("<br />");
      },
    },
    xAxis: { type: "category", data: categories, axisTick: { show: false }, axisLabel: { color: "#666" } },
    yAxis: { type: "value", axisLabel: { color: "#999" }, splitLine: { lineStyle: { color: "rgba(30,58,95,0.08)" } } },
    series,
  };
}
