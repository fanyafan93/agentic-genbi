"use client";

import ReactECharts from "echarts-for-react";
import { toEChartsOption } from "./chart-adapter";
import type { AnalysisRow, ChartSpec } from "@/modules/analysis/types/analysis";

export function EChartRenderer({ spec, rows }: { spec: ChartSpec; rows: AnalysisRow[] }) {
  return <ReactECharts option={toEChartsOption(spec, rows)} style={{ height: 260, width: "100%" }} notMerge />;
}
