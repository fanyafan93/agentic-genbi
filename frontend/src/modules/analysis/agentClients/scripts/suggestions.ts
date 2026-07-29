export type Suggestion = { id: string; title: string; description: string };

export const suggestions: Suggestion[] = [
  { id: "channel", title: "渠道销售占比分析", description: "按渠道拆解上个月销售占比与同比增长" },
  { id: "inventory", title: "库存周转异常排查", description: "定位周转率异常的商品与仓库" },
  { id: "region", title: "华东 GMV 趋势", description: "拆时间看华东区域 GMV 的同比与环比" },
  { id: "monthly", title: "月度经营复盘", description: "自动汇总月初到当下经营关键指标" },
];
