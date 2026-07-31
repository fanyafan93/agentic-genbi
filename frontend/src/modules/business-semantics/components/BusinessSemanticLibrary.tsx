"use client";

const semanticModels = [
  {
    type: "FineReport",
    title: "报表级语义模型",
    description: "解析报表信息、数据集、指标、维度、参数、过滤器和交互逻辑。",
    references: ["报表数据集", "单元格公式", "参数联动", "图表配置"],
    status: "解析器构建中",
  },
  {
    type: "MySQL / Doris",
    title: "数据库元数据语义模型",
    description: "把库、表、字段、注释、主外键候选和分区信息转成 Agent 可检索语义。",
    references: ["information_schema", "字段注释", "分区字段", "指标候选"],
    status: "可检索",
  },
  {
    type: "ETL",
    title: "血缘与加工逻辑语义模型",
    description: "沉淀 Hop 工作流、SQL 脚本、上下游表和字段转换关系。",
    references: ["Apache Hop", "输入输出表", "字段映射", "加工规则"],
    status: "规划中",
  },
  {
    type: "金蝶",
    title: "数据字典语义模型",
    description: "把金蝶业务对象、字段含义和单据关系变成可查证的业务系统语义。",
    references: ["业务对象", "单据字段", "枚举值", "来源系统"],
    status: "待接入",
  },
  {
    type: "SQL 示例",
    title: "历史 SQL 语义模型",
    description: "结合 Vanna 思路，把可靠 SQL 示例、问题表达和字段用法沉淀为可复用样例。",
    references: ["问题样例", "SQL 模板", "字段用法", "过滤条件"],
    status: "mock",
  },
  {
    type: "指标 / 维度",
    title: "指标维度结构",
    description: "记录指标定义、口径版本、可分析维度、默认粒度和适用场景。",
    references: ["GMV", "复购率", "渠道", "SKU"],
    status: "治理中",
  },
];

const businessKnowledge = [
  {
    title: "首购后 30 天复购率排除规则",
    description: "首购后 30 天复购率要排除退款订单、取消订单和测试订单。",
    evidence: "来源：复购率分析任务，业务已确认。",
    status: "已确认",
  },
  {
    title: "华东 GMV 下滑排查经验",
    description: "华东 GMV 下滑通常先看渠道结构、活动节奏和大客户订单波动。",
    evidence: "来源：华东区域 GMV 趋势分析。",
    status: "团队可见",
  },
  {
    title: "渠道销售额字段来源",
    description: "渠道销售额优先使用订单主渠道字段；财务口径需切换收入确认表。",
    evidence: "来源：渠道销售占比分析 SQL 和报表语义查证。",
    status: "待复核",
  },
];

const verificationRecords = [
  "检索业务语义库：命中 FineReport 报表语义、MySQL / Doris 字段和历史 SQL 示例。",
  "语义查证：核对复购率指标口径、退款排除规则和会员 ID 字段来源。",
  "沉淀业务知识：用户确认后写入业务规则和字段来源说明。",
];

export function BusinessSemanticLibrary() {
  return (
    <section className="business-semantic-page" aria-label="业务语义库">
      <header className="semantic-page-hero">
        <span>BUSINESS SEMANTIC LIBRARY</span>
        <h1>业务语义库</h1>
        <p>业务语义库统一承载语义模型和业务知识：让 Agent 看懂数据和系统，也记住被确认的业务经验。</p>
      </header>

      <div className="semantic-page-grid">
        <section className="semantic-section" aria-label="语义模型">
          <div className="semantic-section-header">
            <span>SEMANTIC MODELS</span>
            <h2>语义模型</h2>
            <p>面向 Agent 的结构化理解层，减少它直接猜表、猜字段、猜口径。</p>
          </div>
          <div className="semantic-model-grid">
            {semanticModels.map((model) => (
              <article className="semantic-model-card" key={model.type}>
                <div>
                  <span>{model.type}</span>
                  <strong>{model.title}</strong>
                </div>
                <p>{model.description}</p>
                <div className="semantic-chip-row">
                  {model.references.map((item) => <em key={item}>{item}</em>)}
                </div>
                <small>{model.status}</small>
              </article>
            ))}
          </div>
        </section>

        <section className="semantic-section" aria-label="业务知识">
          <div className="semantic-section-header">
            <span>BUSINESS KNOWLEDGE</span>
            <h2>业务知识</h2>
            <p>用户确认过的口径、规则、字段来源和分析经验，后续分析可直接引用。</p>
          </div>
          <div className="business-knowledge-list">
            {businessKnowledge.map((item) => (
              <article className="business-knowledge-card" key={item.title}>
                <span>{item.status}</span>
                <strong>{item.title}</strong>
                <p>{item.description}</p>
                <small>{item.evidence}</small>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="semantic-verification-records" aria-label="语义查证记录">
        <div>
          <span>BACKGROUND CAPABILITY</span>
          <h2>语义查证记录</h2>
          <p>原探索过程会逐步变成编排层后台能力，在分析工作台里被 Agent 自动调用。</p>
        </div>
        <ol>
          {verificationRecords.map((record) => <li key={record}>{record}</li>)}
        </ol>
      </section>
    </section>
  );
}
