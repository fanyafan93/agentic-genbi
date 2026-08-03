import type { EChartsOption } from "echarts";
import type { AnalysisRow, ChartSpec } from "@/modules/analysis/types/analysis";

function formatValue(value: unknown, format?: string) {
  if (typeof value !== "number") return String(value ?? "");
  if (format === "currency") return `CNY ${value.toLocaleString("zh-CN")}`;
  if (format === "percent") return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString("zh-CN");
}

export function toEChartsOption(spec: ChartSpec, rows: AnalysisRow[]): EChartsOption {
  const categoryField = resolveCategoryField(spec, rows);
  const seriesSpecs = spec.series.map((item) => ({ ...item, field: resolveSeriesField(item.field, rows) }));
  const plottedRows = rows.filter((row) => {
    const hasCategory = String(row[categoryField] ?? "").trim().length > 0;
    const hasValue = seriesSpecs.some((item) => parseChartNumber(row[item.field], item.format) !== null);
    return hasCategory && hasValue;
  });
  const categories = plottedRows.map((row) => String(row[categoryField] ?? ""));
  const series: EChartsOption["series"] = seriesSpecs.map((item) => ({
    name: item.name,
    type: spec.type === "line" ? "line" : "bar",
    data: plottedRows.map((row) => parseChartNumber(row[item.field], item.format)),
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
        const lines = seriesSpecs.map((item) => `${item.name}: ${formatValue(parseChartNumber(plottedRows[dataIndex]?.[item.field], item.format), item.format)}`);
        return [categories[dataIndex], ...lines].join("<br />");
      },
    },
    xAxis: { type: "category", data: categories, axisTick: { show: false }, axisLabel: { color: "#666" } },
    yAxis: { type: "value", axisLabel: { color: "#999" }, splitLine: { lineStyle: { color: "rgba(30,58,95,0.08)" } } },
    series,
    ...(plottedRows.length === 0 ? { graphic: { type: "text", left: "center", top: "middle", style: { text: "暂无可绘制数据", fill: "#667085", fontSize: 13 } } } : {}),
  };
}

function resolveCategoryField(spec: ChartSpec, rows: AnalysisRow[]): string {
  if (rows.some((row) => hasDisplayValue(row[spec.categoryField]))) return spec.categoryField;
  const fields = collectFields(rows);
  const preferred = fields
    .filter((field) => /channel|name|category|渠道|名称|指标/i.test(field))
    .sort((left, right) => displayValueCount(rows, right) - displayValueCount(rows, left))
    .find((field) => displayValueCount(rows, field) > 0);
  if (preferred) return preferred;
  return fields.find((field) => rows.some((row) => hasDisplayValue(row[field]) && parseChartNumber(row[field]) === null)) ?? spec.categoryField;
}

function resolveSeriesField(field: string, rows: AnalysisRow[]): string {
  if (rows.some((row) => parseChartNumber(row[field]) !== null)) return field;
  const fields = collectFields(rows);
  const preferred = fields
    .filter((candidate) => /sales|amount|gmv|revenue|value|销售|金额|数值/i.test(candidate))
    .sort((left, right) => numericValueCount(rows, right) - numericValueCount(rows, left))
    .find((candidate) => numericValueCount(rows, candidate) > 0);
  if (preferred) return preferred;
  return fields.sort((left, right) => numericValueCount(rows, right) - numericValueCount(rows, left))[0] ?? field;
}

function collectFields(rows: AnalysisRow[]): string[] {
  return Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
}

function numericValueCount(rows: AnalysisRow[], field: string): number {
  return rows.filter((row) => parseChartNumber(row[field]) !== null).length;
}

function displayValueCount(rows: AnalysisRow[], field: string): number {
  return rows.filter((row) => hasDisplayValue(row[field])).length;
}

function hasDisplayValue(value: unknown): boolean {
  return String(value ?? "").trim().length > 0;
}

function parseChartNumber(value: unknown, format?: string): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const numeric = Number(trimmed.replace(/[,\s￥¥元件个%]/g, ""));
  if (!Number.isFinite(numeric)) return null;
  return format === "percent" || trimmed.includes("%") ? numeric / 100 : numeric;
}
