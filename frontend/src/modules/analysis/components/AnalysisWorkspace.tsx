"use client";

import { useState } from "react";
import { EChartRenderer } from "@/shared/charts/EChartRenderer";
import { useAnalysisRun } from "../hooks/use-analysis-run";
import type { AnalysisRow } from "../types/analysis";

const navItems = [
  { id: "workspace", label: "工作台", icon: "⌁" },
  { id: "sessions", label: "会话", icon: "◇" },
  { id: "datasource", label: "数据", icon: "▦" },
  { id: "system", label: "系统", icon: "⚙" },
];

function formatCell(value: AnalysisRow[string]) {
  if (typeof value !== "number") return value;
  if (Math.abs(value) < 1) return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString("zh-CN");
}

export function AnalysisWorkspace() {
  const { run, isLoading } = useAnalysisRun();
  const [activeTool, setActiveTool] = useState("workspace");
  const [collapsed, setCollapsed] = useState(false);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);

  const mode = activeTool === "sessions" ? (selectedSession ? "session" : "empty") : "default";

  return (
    <div className="app-shell">
      <header className="topbar">
        <img className="topbar-logo" src="/brand-logo.png" alt="Agentic GenBI" />
        <div className="topbar-slogan" aria-label="Make sense of your data">
          <span>MAKE SENSE</span><span className="connector">OF</span><span className="emph">YOUR DATA</span>
        </div>
        <span />
      </header>

      <div className={`shell ${collapsed ? "collapsed" : ""}`}>
        <nav className="icon-toolbar" aria-label="主导航">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`icon-btn ${!collapsed && activeTool === item.id ? "active" : ""}`}
              type="button"
              title={item.label}
              aria-label={item.label}
              onClick={() => {
                if (activeTool === item.id && !collapsed) {
                  setCollapsed(true);
                  return;
                }
                setActiveTool(item.id);
                setCollapsed(false);
              }}
            >
              <span>{item.icon}</span>
            </button>
          ))}
          <div className="spacer" />
          <button className="icon-toolbar-user" type="button" aria-label="账户">J</button>
        </nav>

        <aside className={`panel ${activeTool === "sessions" ? "sessions" : ""}`} aria-label="侧栏">
          {activeTool === "sessions" ? (
            <div className="session-panel">
              <header className="panel-header"><span className="panel-kicker">CONVERSATIONS</span><h2>会话</h2></header>
              <button className="session-new" type="button" onClick={() => setSelectedSession(null)}><span>+ 新建会话</span><span>⌘ K</span></button>
              {["渠道销售占比分析", "库存周转异常排查", "华东区域 GMV 趋势", "月度经营复盘"].map((title, index) => (
                <button key={title} className={`session-item ${selectedSession === title ? "active" : ""}`} type="button" onClick={() => setSelectedSession(title)}>
                  <strong>{title}</strong><span>{index < 2 ? "今天" : "更早"}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="workbench-panel"><div className="placeholder"><span>⌁</span><strong>待开发</strong></div></div>
          )}
        </aside>

        <button className="panel-toggle" type="button" aria-label="收起侧栏" onClick={() => setCollapsed(true)}>‹</button>

        <main className="main" data-mode={mode}>
          <div className="workspace-empty">
            <div className="placeholder"><span>◇</span><strong>{activeTool === "sessions" ? "选择一个会话，或新建一个会话开始" : "待开发"}</strong></div>
          </div>

          {run && (
            <section className="workspace">
              <div className="thread">
                <header className="thread-header"><span>CONVERSATION</span><h1>#{run.id}</h1><em>{run.status === "needs_input" ? "等待补充" : "分析中"}</em></header>
                <div className="thread-scroll">
                  <article className="node user"><b>你</b><p>{run.question}</p></article>
                  <article className="node agent"><b>Agent</b><p>我先理解需求、查询口径，并生成可校验 SQL。</p>
                    <ul className="step-list">{run.steps.map((step) => <li key={step.label} className={step.state}><span />{step.label}<em>{step.state}</em></li>)}</ul>
                  </article>
                  <article className="node followup"><b>Agent 追问</b><p>你想按销售额、毛利率还是订单数衡量渠道表现？</p><div className="chips"><button>销售额</button><button>毛利率</button><button>订单数</button></div></article>
                </div>
                <form className="composer"><textarea placeholder="有什么问题，或想继续探索什么？" rows={3} /><button type="button" aria-label="发送">↑</button></form>
              </div>

              <div className="output">
                <header className="output-header"><span>OUTPUT</span><h2>渠道销售占比分析</h2></header>
                <div className="chart-picker"><button className="active">Bar Chart</button><button>Line Chart</button><button>Pie Chart</button><button>Table</button></div>
                <div className="output-body">
                  <aside className="insight"><h3>关键洞察</h3><ul>{run.insight.map((item) => <li key={item}>{item}</li>)}</ul></aside>
                  <div className="chart-area"><EChartRenderer spec={run.chart} rows={run.table} /></div>
                </div>
                <pre className="sql-panel">{run.sql}</pre>
                <table className="data-table"><thead><tr>{Object.keys(run.table[0]).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{run.table.map((row) => <tr key={String(row.channel)}>{Object.values(row).map((value, index) => <td key={index}>{formatCell(value)}</td>)}</tr>)}</tbody></table>
              </div>
            </section>
          )}

          {isLoading && <div className="workspace-empty"><div className="placeholder"><strong>加载中</strong></div></div>}
        </main>
      </div>
    </div>
  );
}
