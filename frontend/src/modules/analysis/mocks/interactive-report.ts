import type { InteractiveReport, ReportDatasetRow, ReportRuntimeFilters } from "../types/interactive-report";

export const channelSalesReportQueryRef = "finereport-operation-management-channel-sales";

export const mockInteractiveReport: InteractiveReport = {
  artifactType: "interactive_report",
  schemaVersion: "1.0",
  id: "report_channel_mix_2026_08",
  title: "渠道销售结构与增长分析",
  subtitle: "识别 2026 年 8 月销售增长的主要渠道贡献，并定位需要继续验证的异常。",
  renderer: "puck",
  source: {
    threadId: "conv_analysis_channel",
    turnId: "turn_channel_202608",
  },
  filters: [
    { id: "month", label: "月份", defaultValue: "2026-05", options: [{ label: "2026年4月", value: "2026-04" }, { label: "2026年5月", value: "2026-05" }] },
    { id: "brand", label: "品牌", defaultValue: "all", options: [{ label: "全部品牌", value: "all" }, { label: "花西子", value: "花西子" }, { label: "彩棠", value: "彩棠" }] },
    { id: "region", label: "区域", defaultValue: "all", options: [{ label: "全部区域", value: "all" }, { label: "华东", value: "华东" }, { label: "华南", value: "华南" }] },
  ],
  document: {
    root: { props: { title: "渠道销售结构与增长分析" } },
    content: [
      { type: "SectionBlock", props: { id: "summary-section", title: "本期结论", tone: "coral" } },
      { type: "MarkdownBlock", props: { id: "summary-note", content: "线上直营仍是最大渠道，贡献了本期约四成销售额；社交电商增速最快，但基数较小。建议下一步核对线上分销的毛利结构和投放效率。" } },
      { type: "KpiBlock", props: { id: "kpi-sales", metric: "sales" } },
      { type: "KpiBlock", props: { id: "kpi-share", metric: "share" } },
      { type: "KpiBlock", props: { id: "kpi-growth", metric: "growth" } },
      { type: "SectionBlock", props: { id: "trend-section", title: "渠道贡献", tone: "navy" } },
      { type: "ChartBlock", props: { id: "channel-chart", chartSpecRef: "channel-sales-chart", queryRef: channelSalesReportQueryRef } },
      { type: "SectionBlock", props: { id: "detail-section", title: "渠道明细", tone: "navy" } },
      { type: "GridBlock", props: { id: "channel-grid", gridSpecRef: "channel-sales-grid", queryRef: channelSalesReportQueryRef } },
      { type: "EvidenceBlock", props: { id: "evidence", label: "证据与假设", content: "数据来自 mart_sales_channel_month；退款排除口径待业务确认。报告中的筛选仅改变运行状态，不生成新版本。" } },
    ],
    zones: {},
  },
  queries: {
    [channelSalesReportQueryRef]: { datasetId: "channel_sales", filterBindings: ["month", "brand", "region"] },
  },
  chartSpecs: {
    "channel-sales-chart": {
      id: "channel-sales-chart",
      datasetId: "channel_sales",
      type: "bar",
      xField: "channel",
      title: "渠道销售额",
      series: [{ field: "salesAmount", label: "销售额", format: "currency" }],
    },
  },
  gridSpecs: {
    "channel-sales-grid": {
      id: "channel-sales-grid",
      datasetId: "channel_sales",
      pageSize: 8,
      columns: [
        { field: "channel", label: "渠道" },
        { field: "salesAmount", label: "销售额", format: "currency" },
        { field: "salesShare", label: "销售占比", format: "percent" },
      { field: "netRevenue", label: "收入净额", format: "currency" },
      { field: "refundAmount", label: "退款金额", format: "currency" },
      ],
    },
  },
};

const rows: Array<ReportDatasetRow & { month: string; brand: string; region: string }> = [
  { month: "2026-05", brand: "花西子", region: "华东", channel: "线上直营", salesAmount: 14575200, salesShare: 0.42, growth: 0.129, status: "稳定增长" },
  { month: "2026-05", brand: "花西子", region: "华东", channel: "线下加盟", salesAmount: 8920400, salesShare: 0.257, growth: 0.284, status: "重点跟进" },
  { month: "2026-05", brand: "花西子", region: "华南", channel: "电商平台", salesAmount: 6310500, salesShare: 0.182, growth: 0.062, status: "平稳" },
  { month: "2026-05", brand: "彩棠", region: "华东", channel: "社交电商", salesAmount: 3180100, salesShare: 0.092, growth: 0.447, status: "高增速" },
  { month: "2026-05", brand: "彩棠", region: "华南", channel: "其他", salesAmount: 1690800, salesShare: 0.049, growth: -0.031, status: "需要复核" },
  { month: "2026-04", brand: "花西子", region: "华东", channel: "线上直营", salesAmount: 13123300, salesShare: 0.414, growth: 0.085, status: "稳定增长" },
  { month: "2026-04", brand: "花西子", region: "华东", channel: "线下加盟", salesAmount: 8411000, salesShare: 0.265, growth: 0.211, status: "重点跟进" },
  { month: "2026-04", brand: "花西子", region: "华南", channel: "电商平台", salesAmount: 5962300, salesShare: 0.188, growth: 0.053, status: "平稳" },
  { month: "2026-04", brand: "彩棠", region: "华东", channel: "社交电商", salesAmount: 2876600, salesShare: 0.091, growth: 0.332, status: "高增速" },
  { month: "2026-04", brand: "彩棠", region: "华南", channel: "其他", salesAmount: 1568600, salesShare: 0.042, growth: -0.014, status: "需要复核" },
];

export function createDefaultReportFilters(report: InteractiveReport = mockInteractiveReport): ReportRuntimeFilters {
  return Object.fromEntries(report.filters.map((filter) => [filter.id, filter.defaultValue])) as ReportRuntimeFilters;
}

export function queryMockDataset(datasetId: string, filters: ReportRuntimeFilters): ReportDatasetRow[] {
  if (datasetId !== "channel_sales") return [];
  const result = rows.filter((row) => (
    row.month === filters.month
    && (filters.brand === "all" || row.brand === filters.brand)
    && (filters.region === "all" || row.region === filters.region)
  ));
  const total = result.reduce((sum, row) => sum + Number(row.salesAmount), 0);
  return result.map(({ month: _month, brand: _brand, region: _region, ...row }) => ({
    ...row,
    netRevenue: Number(row.salesAmount) * 0.85,
    refundAmount: Number(row.salesAmount) * 0.03,
    salesShare: total ? Number(row.salesAmount) / total : 0,
  }));
}
