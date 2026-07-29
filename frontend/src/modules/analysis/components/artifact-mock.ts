import type { AnalysisRow, ChartSpec } from "../types/analysis";

export const mockArtifact = {
  metrics: [
    { label: "销售额", value: "3,467 万", delta: "+18.6%" },
    { label: "主渠道占比", value: "42.0%", delta: "线上直营" },
    { label: "最快增长", value: "44.7%", delta: "社交电商" },
  ],
  insights: [
    "线上直营渠道占比 42.0%，是当前最大销售渠道。",
    "社交电商同比增长 44.7%，增速最快但基数仍小。",
    "建议继续拆解线上分销与社交电商的毛利结构。",
  ],
  chart: {
    type: "bar" as const,
    title: "渠道销售占比",
    categoryField: "channel",
    series: [{ field: "sales_amount", name: "销售额", format: "currency" }],
  } satisfies ChartSpec,
  table: [
    { channel: "线上直营", sales_amount: 14575200, sales_share: 0.42, yoy_growth: 0.129 },
    { channel: "线下加盟", sales_amount: 8920400, sales_share: 0.257, yoy_growth: 0.284 },
    { channel: "电商平台", sales_amount: 6310500, sales_share: 0.182, yoy_growth: 0.062 },
    { channel: "社交电商", sales_amount: 3180100, sales_share: 0.092, yoy_growth: 0.447 },
    { channel: "其他", sales_amount: 1690800, sales_share: 0.049, yoy_growth: -0.031 },
  ] satisfies AnalysisRow[],
  sql: `select channel, sales_amount, sales_share, yoy_growth
from mart_sales_channel_month
where month = '2026-06'
order by sales_amount desc
limit 5;`,
};
