import type { ArtifactFolder } from "../../types/artifact";
import type { FlowNode } from "../../hooks/use-flow";

export type SessionScript = {
  id: string;
  title: string;
  messages: FlowNode[];
  artifacts: ArtifactFolder[];
};

const channelArtifacts: ArtifactFolder[] = [
  { id: "reports", name: "reports", children: [{ id: "report", name: "Report.html", kind: "html" }, { id: "summary", name: "summary.md", kind: "markdown" }] },
  { id: "queries", name: "queries", children: [{ id: "channel-sales", name: "channel_sales.sql", kind: "sql" }, { id: "validation", name: "validation.sql", kind: "sql" }] },
  { id: "scripts", name: "scripts", children: [{ id: "analysis", name: "analysis.py", kind: "python" }] },
  { id: "data", name: "data", children: [{ id: "result", name: "result.csv", kind: "csv" }, { id: "metadata", name: "metadata.json", kind: "json" }] },
];

const channelMessages: FlowNode[] = [
  { id: "user-1", role: "user", content: "请基于当前数据，分析上个月各渠道的销售占比，并指出增长最快的渠道。" },
  {
    id: "agent-1",
    role: "agent",
    content: "我先理解需求、查询口径，并生成可校验 SQL。",
    steps: [
      { label: "识别业务口径", state: "done" },
      { label: "查询可用数据表", state: "done" },
      { label: "生成并校验 SQL", state: "running" },
      { label: "整理图表与结论", state: "queued" },
    ],
  },
  { id: "user-2", role: "user", content: "按销售额衡量。请用最新一整年的数据拆分。" },
  {
    id: "agent-2",
    role: "agent",
    content: "好的，准备拉取 2025-07 ~ 2026-06 的渠道销售数据。",
    steps: [
      { label: "读取数据表", state: "done" },
      { label: "校验口径", state: "done" },
      { label: "生成 SQL", state: "done" },
      { label: "渲染图表", state: "done" },
    ],
  },
  { id: "agent-3", role: "agent", content: "关键发现：线上直营占比 42.0%，社交电商同比增速 44.7%（基数小）。" },
  { id: "user-3", role: "user", content: "社交电商的增长驱动来自哪里？拆一下来源。" },
  { id: "agent-4", role: "agent", content: "已按细分渠道拆分，社交电商增长主要由短视频带货贡献，占新增 GMV 的 71%。" },
  {
    id: "ask-1",
    role: "ask",
    question: "想怎么处理这个发现？",
    options: [
      { id: "继续", label: "继续深挖" },
      { id: "报告", label: "出新报告" },
      { id: "审批", label: "创建审批" },
    ],
    current: true,
  },
];

const inventoryArtifacts: ArtifactFolder[] = [
  { id: "queries", name: "queries", children: [{ id: "inventory-slow", name: "inventory_slow.sql", kind: "sql" }] },
  { id: "data", name: "data", children: [{ id: "inventory-csv", name: "inventory_slow.csv", kind: "csv" }] },
];

const inventoryMessages: FlowNode[] = [
  { id: "user-1", role: "user", content: "帮我看下最近 14 天哪些 SKU 库存周转明显放慢。" },
  {
    id: "agent-1",
    role: "agent",
    content: "正在按周转天数环比拆解，已经定位到 3 个仓库。",
    steps: [
      { label: "读取库存事实表", state: "done" },
      { label: "扫描异常 SKU", state: "running" },
      { label: "汇总仓库归因", state: "queued" },
    ],
  },
  {
    id: "ask-1",
    role: "ask",
    question: "接下来想怎么继续？",
    options: [
      { id: "下钻", label: "下钻到仓库" },
      { id: "对比", label: "对比同期" },
      { id: "出报告", label: "出报告" },
    ],
    current: true,
  },
];

const regionArtifacts: ArtifactFolder[] = [
  { id: "reports", name: "reports", children: [{ id: "report", name: "Report.html", kind: "html" }] },
  { id: "data", name: "data", children: [{ id: "region-csv", name: "region_gmv.csv", kind: "csv" }] },
];

const regionMessages: FlowNode[] = [
  { id: "user-1", role: "user", content: "对比下华东地区本月与上月 GMV 走势。" },
  {
    id: "agent-1",
    role: "agent",
    content: "华东本月 GMV +8.2%，主要由线上分销带动，线下有个别门店拖累。",
  },
];

const monthlyArtifacts: ArtifactFolder[] = [
  { id: "reports", name: "reports", children: [{ id: "report", name: "Report.html", kind: "html" }, { id: "summary", name: "summary.md", kind: "markdown" }] },
];

const monthlyMessages: FlowNode[] = [
  { id: "user-1", role: "user", content: "给我一份这个月的经营复盘。" },
  { id: "agent-1", role: "agent", content: "已生成月度复盘要点，关键指标摘要附在报告里。" },
];

export const sessionScripts: SessionScript[] = [
  { id: "channel", title: "渠道销售占比分析", messages: channelMessages, artifacts: channelArtifacts },
  { id: "inventory", title: "库存周转异常排查", messages: inventoryMessages, artifacts: inventoryArtifacts },
  { id: "region", title: "华东区域 GMV 趋势", messages: regionMessages, artifacts: regionArtifacts },
  { id: "monthly", title: "月度经营复盘", messages: monthlyMessages, artifacts: monthlyArtifacts },
];

export function findSessionByTitle(title: string): SessionScript | undefined {
  return sessionScripts.find((s) => s.title === title);
}
