"use client";

import { useEffect, useState } from "react";
import {
  listBackendMcpServers,
  testBackendMcpServer,
  type BackendMcpServer,
} from "../agentClients/backendClient";

type TestState = Record<string, { status: string; message: string; ok: boolean }>;

export function SystemMcpPage() {
  const [servers, setServers] = useState<BackendMcpServer[]>([]);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [disabled, setDisabled] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [tests, setTests] = useState<TestState>({});

  async function refreshServers() {
    setLoading(true);
    try {
      const next = await listBackendMcpServers();
      setServers(next);
      setExpanded((current) => current.length > 0 ? current : next.slice(0, 1).map((server) => server.name));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshServers();
  }, []);

  async function testServer(name: string) {
    setTests((state) => ({ ...state, [name]: { ok: false, status: "testing", message: "Testing connection..." } }));
    try {
      const result = await testBackendMcpServer(name);
      setTests((state) => ({ ...state, [name]: result }));
    } catch (error) {
      setTests((state) => ({
        ...state,
        [name]: {
          ok: false,
          status: "failed",
          message: error instanceof Error ? error.message : "Connection test failed.",
        },
      }));
    }
  }

  function toggleExpanded(name: string) {
    setExpanded((items) => items.includes(name) ? items.filter((item) => item !== name) : [...items, name]);
  }

  function toggleEnabled(name: string) {
    setDisabled((items) => items.includes(name) ? items.filter((item) => item !== name) : [...items, name]);
  }

  return (
    <section className="system-mcp-page" aria-label="MCP Servers 管理">
      <header>
        <div>
          <span>SYSTEM</span>
          <h1>MCP Servers 管理</h1>
          <p>管理当前 Codex 可见的 MCP 服务，查看工具、状态、权限和 GenBI 信任边界。</p>
        </div>
        <div className="system-mcp-actions">
          <button type="button" onClick={() => { void refreshServers(); }} disabled={loading} title="刷新">↻</button>
        </div>
      </header>

      <div className="mcp-server-list">
        {servers.length === 0 && (
          <div className="mcp-empty">
            <strong>{loading ? "正在加载 MCP 配置" : "暂无 MCP Server"}</strong>
            <small>请检查 GENBI_CODEX_MCP_* 环境变量。</small>
          </div>
        )}
        {servers.map((server) => {
          const isOpen = expanded.includes(server.name);
          const isEnabled = server.enabled && !disabled.includes(server.name);
          const test = tests[server.name];
          return (
            <article className="mcp-server-card" key={server.name} data-open={isOpen} data-enabled={isEnabled}>
              <header>
                <button className="mcp-disclosure" type="button" aria-label={isOpen ? "收起工具" : "展开工具"} onClick={() => toggleExpanded(server.name)}>
                  {isOpen ? "⌄" : "›"}
                </button>
                <span className="mcp-server-icon" aria-hidden="true">{server.name.slice(0, 1).toUpperCase()}</span>
                <div className="mcp-server-title">
                  <strong>{server.name}</strong>
                  <small>{server.command} {server.args.join(" ")}</small>
                </div>
                <span className={`mcp-status ${server.status}`}>{server.status}</span>
                {server.trusted && <span className="mcp-trusted">trusted</span>}
                <button className="mcp-test" type="button" onClick={() => { void testServer(server.name); }}>测试连接</button>
                <button className="mcp-switch" type="button" aria-pressed={isEnabled} onClick={() => toggleEnabled(server.name)}>
                  <span />
                </button>
              </header>

              <div className="mcp-server-meta">
                <span>权限：{server.permission}</span>
                <span>审批：{server.approval}</span>
                <span>环境变量：{server.envKeys.length ? server.envKeys.join(", ") : "无"}</span>
              </div>
              <p className="mcp-server-message">{test?.message || server.message}</p>

              {isOpen && (
                <div className="mcp-tool-table">
                  {server.tools.map((tool) => (
                    <div className="mcp-tool-row" key={tool.name}>
                      <strong>{tool.name}</strong>
                      <span>{tool.description}</span>
                      <em>{tool.permission}</em>
                    </div>
                  ))}
                  {server.tools.length === 0 && <div className="mcp-tool-row empty">暂无已知工具清单</div>}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
