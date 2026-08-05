"use client";

import { useEffect, useState } from "react";

import type { BackendMcpServer } from "@/modules/analysis/agentClients/backendClient";
import {
  listManagedMcpServers,
  testManagedMcpServer,
  updateMcpServerEnabled,
} from "../system-api";

type TestResult = { ok: boolean; status: string; message: string };

export function SystemMcpPanel() {
  const [servers, setServers] = useState<BackendMcpServer[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      const rows = await listManagedMcpServers();
      setServers(rows);
      setSelected((current) => current || rows[0]?.name || null);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "服务加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function toggle(server: BackendMcpServer) {
    const enabled = !server.enabled;
    setMessage("正在应用策略...");
    try {
      await updateMcpServerEnabled(server.name, enabled);
      setServers((current) =>
        current.map((entry) =>
          entry.name === server.name ? { ...entry, enabled } : entry,
        ),
      );
      setMessage(enabled ? "服务已启用，将用于后续分析" : "服务已停用，后续分析不再加载");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "策略更新失败");
    }
  }

  async function test(server: BackendMcpServer) {
    setTests((current) => ({
      ...current,
      [server.name]: { ok: false, status: "testing", message: "正在检查..." },
    }));
    try {
      const result = await testManagedMcpServer(server.name);
      setTests((current) => ({ ...current, [server.name]: result }));
    } catch (error) {
      setTests((current) => ({
        ...current,
        [server.name]: {
          ok: false,
          status: "failed",
          message: error instanceof Error ? error.message : "检查失败",
        },
      }));
    }
  }

  const current = servers.find((server) => server.name === selected) || null;
  const enabledCount = servers.filter((server) => server.enabled).length;

  return (
    <div className="system-domain-panel">
      <div className="system-section-heading">
        <div><span>CONNECTIONS</span><h2>MCP 服务</h2></div>
        <p>管理分析可调用的外部能力、权限与信任边界。</p>
      </div>
      <div className="system-stat-strip">
        <div><span>已配置</span><strong>{servers.length}</strong></div>
        <div><span>已启用</span><strong>{enabledCount}</strong></div>
        <div><span>受信任</span><strong>{servers.filter((server) => server.trusted).length}</strong></div>
      </div>
      <div className="system-master-detail">
        <div className="system-master-list">
          <header><strong>服务清单</strong><button type="button" onClick={() => void refresh()}>刷新</button></header>
          {servers.map((server) => (
            <button
              type="button"
              key={server.name}
              className={selected === server.name ? "active" : ""}
              onClick={() => setSelected(server.name)}
            >
              <span className="system-server-monogram">{server.name.slice(0, 1).toUpperCase()}</span>
              <span><strong>{server.name}</strong><small>{server.tools.length} 个工具</small></span>
              <i className={server.enabled ? "online" : ""} />
            </button>
          ))}
          {!loading && servers.length === 0 && <p className="system-empty">暂无服务</p>}
        </div>
        <div className="system-detail-card">
          {current ? (
            <>
              <header>
                <div><span>服务详情</span><h3>{current.name}</h3></div>
                <button
                  className={`system-switch ${current.enabled ? "on" : ""}`}
                  type="button"
                  aria-label={`${current.enabled ? "停用" : "启用"} ${current.name}`}
                  onClick={() => void toggle(current)}
                ><span /></button>
              </header>
              <div className="system-badge-row">
                <span>{current.status}</span>
                <span>{current.permission}</span>
                <span>{current.approval === "trusted" ? "受信任" : "需要审批"}</span>
              </div>
              <dl className="system-definition-list">
                <div><dt>启动命令</dt><dd>{current.command} {current.args.join(" ")}</dd></div>
                <div><dt>环境变量</dt><dd>{current.envKeys.join(" · ") || "无"}</dd></div>
              </dl>
              <section className="system-tool-list">
                <header><strong>可用工具</strong><span>{current.tools.length}</span></header>
                {current.tools.map((tool) => (
                  <div key={tool.name}>
                    <span><strong>{tool.name}</strong><small>{tool.description}</small></span>
                    <em>{tool.permission}</em>
                  </div>
                ))}
              </section>
              <footer>
                <button type="button" onClick={() => void test(current)}>运行检查</button>
                <p className={tests[current.name]?.ok ? "ok" : ""}>
                  {tests[current.name]?.message || current.message}
                </p>
              </footer>
            </>
          ) : <div className="system-empty">选择一个服务查看详情</div>}
        </div>
      </div>
      {message && <p className="system-inline-message" role="status">{message}</p>}
    </div>
  );
}
