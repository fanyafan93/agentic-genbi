import { mockArtifact } from "./artifact-mock";
import type { ArtifactFile, ArtifactFolder } from "../types/artifact";

export type AnalysisAssetCard = {
  id: string;
  title: string;
  label: string;
  description: string;
  status: "draft" | "confirmed" | "reusable";
  intent?: "save" | "continue" | "edit-skill";
  confirmations?: string[];
  fileId?: string;
};

export const pythonCode = `import pandas as pd

frame = pd.read_csv("data/result.csv")
channel_summary = frame.sort_values("sales_amount", ascending=False)
fastest_growth = frame.loc[frame["yoy_growth"].idxmax(), "channel"]
print(f"增长最快渠道: {fastest_growth}")`;

const markdownSummary = `# 渠道销售占比分析\n\n线上直营为当前最大渠道，社交电商同比增速最快。`;

const metadataJson = `{"source":"mart_sales","month":"2026-06","rows":5,"validated":true}`;

const chartSpecJson = `{
  "type": "bar",
  "title": "渠道销售占比",
  "encodings": {
    "x": { "field": "channel" },
    "y": { "field": "sales_amount" }
  }
}`;

const dashboardSpecJson = `{
  "title": "渠道销售分析 Dashboard 片段",
  "layout": ["channel_share", "growth_rank", "assumption_risks"],
  "refresh": "manual",
  "sourceAssets": ["candidate.sql", "channel_share.chart.json"]
}`;

const assumptionsMarkdown = `# 分析假设

- 暂按支付成功订单计算销售额。
- 暂未排除退款、取消和测试订单。
- 渠道归因优先使用订单主渠道字段。
- 保存为正式资产前建议确认口径。`;

const metricMarkdown = `# 渠道销售额指标口径

## 当前口径
按订单支付成功金额汇总渠道销售额，渠道优先取订单主渠道字段。

## 待确认
- 是否排除退款、取消和测试订单。
- 是否按财务确认收入替代支付金额。
- 是否需要拆分平台、门店、SKU 或新老用户。`;

const ruleMarkdown = `# 订单范围业务规则

## 当前规则
当前草稿暂保留所有支付成功订单，未正式排除退款、取消和测试订单。

## 风险
该规则会影响销售额、渠道占比和增长判断；沉淀为正式资产前需要业务确认。`;

const pathMarkdown = `# 渠道销售占比分析路径

1. 识别业务问题：判断为经营分析 / 渠道结构拆解。
2. 检索业务语义库：优先查报表级语义模型、MySQL / Doris 元数据、ETL 血缘和历史 SQL 示例。
3. 生成候选 SQL：先出可运行草稿，再标注假设。
4. 生成图表和报告：输出渠道占比、增长最快渠道和风险说明。
5. 用户继续追问时，沿当前资产版本修改 SQL、图表、报告或生成 Skill。`;

const skillMarkdown = `# 渠道销售占比分析 Skill

## 适用场景
当用户询问渠道销售占比、渠道增长来源或渠道结构变化时使用。

## 需要确认
- 销售额口径：支付成功、发货、还是财务确认收入。
- 时间范围：自然月、滚动周期、还是活动周期。
- 是否排除退款、取消、测试订单。
- 是否需要按门店、平台、SKU 或新老用户继续拆分。
- 是否允许把当前分析路径发布给团队复用。
- 后续 Agent 运行时是否必须先追问口径，还是允许先生成假设草稿。

## 推荐步骤
1. 确认业务口径和分析范围。
2. 检索业务语义库，读取报表级语义模型、数据库元数据、ETL 血缘和历史 SQL 示例。
3. 生成只读 SQL，并校验表、字段、过滤条件和 limit。
4. 生成渠道占比图表和结果表。
5. 输出结论、假设、风险和下一步追问。
6. 如果用户要求复用，把本次路径、确认项和资产引用沉淀为 Skill。`;

export function mergeArtifactFolders(base: ArtifactFolder[], generated: ArtifactFolder[]) {
  const folders = base.map((folder) => ({
    ...folder,
    children: folder.children.map((file) => ({ ...file })),
  }));
  for (const generatedFolder of generated) {
    let target = folders.find((folder) => folder.id === generatedFolder.id);
    if (!target) {
      target = { id: generatedFolder.id, name: generatedFolder.name, children: [] };
      folders.push(target);
    }
    for (const file of generatedFolder.children) {
      const existing = target.children.findIndex((item) => item.id === file.id);
      if (existing >= 0) target.children[existing] = file;
      else target.children.push(file);
    }
  }
  return folders;
}

export function getMarkdownPreview(file: ArtifactFile) {
  if (file.name.toLowerCase().includes("skill")) return skillMarkdown;
  if (file.name.toLowerCase().includes("assumption")) return assumptionsMarkdown;
  if (file.name.toLowerCase().includes("metric")) return metricMarkdown;
  if (file.name.toLowerCase().includes("rule")) return ruleMarkdown;
  if (file.name.toLowerCase().includes("path")) return pathMarkdown;
  return markdownSummary;
}

export function getSqlPreview(file: ArtifactFile) {
  if (file.name.includes("quick")) {
    return `select channel, sum(pay_amount) as sales_amount
from dws_order_channel_day
where pay_date between '2026-06-01' and '2026-06-30'
group by channel
order by sales_amount desc
limit 20;`;
  }
  if (file.id === "validation") return `select count(*) as row_count from mart_sales_channel_month where month = '2026-06';`;
  if (file.name.includes("revised")) {
    return `select channel, week_start, sum(pay_amount) as sales_amount
from dws_order_channel_day
where pay_date >= '2026-06-01'
  and is_test_order = 0
group by channel, week_start
order by week_start, sales_amount desc
limit 200;`;
  }
  return mockArtifact.sql;
}

export function getJsonPreview(file: ArtifactFile) {
  if (file.name.includes("dashboard")) return dashboardSpecJson;
  if (file.name.includes("chart")) return chartSpecJson;
  return metadataJson;
}

export function describeArtifact(file: ArtifactFile) {
  if (file.name.toLowerCase().includes("skill")) return { label: "Skill", description: "可复用分析方法" };
  if (file.name.toLowerCase().includes("assumption")) return { label: "假设", description: "待确认业务口径" };
  if (file.name.toLowerCase().includes("metric")) return { label: "指标口径", description: "可治理口径定义" };
  if (file.name.toLowerCase().includes("rule")) return { label: "业务规则", description: "可复用判断条件" };
  if (file.name.toLowerCase().includes("path")) return { label: "分析路径", description: "可复用工作步骤" };
  if (file.name.toLowerCase().includes("dashboard")) return { label: "Dashboard", description: "可组合看板片段" };
  if (file.name.includes("chart")) return { label: "图表", description: "可复用可视化配置" };
  if (file.kind === "html") return { label: "报告", description: "可分享分析报告" };
  if (file.kind === "sql") return { label: "SQL", description: "可验证查询资产" };
  if (file.kind === "python") return { label: "Python", description: "复杂分析脚本" };
  if (file.kind === "csv") return { label: "数据", description: "结果快照" };
  return { label: file.kind.toUpperCase(), description: "结构化分析资产" };
}

export function buildAnalysisAssetCards(files: ArtifactFile[]): AnalysisAssetCard[] {
  const findFile = (matcher: (file: ArtifactFile) => boolean) => files.find(matcher);
  const cards: AnalysisAssetCard[] = [];
  const report = findFile((file) => file.kind === "html");
  const sql = findFile((file) => file.kind === "sql");
  const chart = findFile((file) => file.name.includes("chart"));
  const metric = findFile((file) => file.name.toLowerCase().includes("metric"));
  const rule = findFile((file) => file.name.toLowerCase().includes("rule"));
  const path = findFile((file) => file.name.toLowerCase().includes("path"));
  const dashboard = findFile((file) => file.name.toLowerCase().includes("dashboard"));
  const skill = findFile((file) => file.name.toLowerCase().includes("skill"));
  const assumptions = findFile((file) => file.name.toLowerCase().includes("assumption"));

  const pushCard = (card: AnalysisAssetCard | false | undefined) => {
    if (card) cards.push(card);
  };

  pushCard(report && { id: "report", title: "分析报告", label: "报告", description: "可分享给业务方的结论页", status: "draft", intent: "save", fileId: report.id });
  pushCard(sql && { id: "sql", title: "可验证 SQL", label: "SQL", description: "支持复跑和口径核验的查询", status: "draft", intent: "save", fileId: sql.id });
  pushCard(chart && { id: "chart", title: "图表配置", label: "图表", description: "可复用到报告或 dashboard", status: "draft", intent: "save", fileId: chart.id });
  pushCard(metric && { id: "metric", title: "指标口径", label: "口径", description: "沉淀销售额、占比等定义", status: "draft", intent: "save", fileId: metric.id });
  pushCard(rule && { id: "rule", title: "业务规则", label: "规则", description: "记录退款、测试订单等排除规则", status: "draft", intent: "save", fileId: rule.id });
  pushCard(path && { id: "path", title: "分析路径", label: "路径", description: "把本次拆解步骤变成可复用流程", status: "reusable", intent: "continue", fileId: path.id });
  pushCard(dashboard && { id: "dashboard", title: "Dashboard 片段", label: "看板", description: "可组合到后续分析看板", status: "draft", intent: "save", fileId: dashboard.id });
  pushCard(skill && {
    id: "skill",
    title: "Skill.md",
    label: "Skill",
    description: "把成功分析变成可复用分析方法",
    status: "reusable",
    intent: "edit-skill",
    confirmations: ["口径确认", "适用场景", "复用权限"],
    fileId: skill.id,
  });
  pushCard(assumptions && { id: "assumptions", title: "假设与风险", label: "假设", description: "当前草稿里未确认的业务前提", status: "draft", intent: "save", fileId: assumptions.id });

  return cards;
}
