"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  createManagedMcpServer,
  deleteManagedMcpServer,
  listManagedMcpServers,
  revealManagedMcpSecrets,
  testManagedMcpServer,
  updateManagedMcpServer,
  updateMcpServerEnabled,
  type ManagedMcpEnvironment,
  type ManagedMcpInput,
  type ManagedMcpServer,
} from "../system-api";

type Filter = "all" | "system" | "external";
type TestResult = { ok: boolean; status: string; message: string };
type EditorState = { mode: "create" | "edit"; server?: ManagedMcpServer } | null;

const emptyInput: ManagedMcpInput = {
  name: "",
  displayName: "",
  transport: "stdio",
  command: "",
  args: [],
  url: "",
  bearerTokenEnvVar: "",
  bearerToken: "",
  oauthClientId: "",
  oauthResource: "",
  environment: [],
  enabled: true,
};

export function SystemMcpPanel() {
  const [servers, setServers] = useState<ManagedMcpServer[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [editor, setEditor] = useState<EditorState>(null);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const hideSecretsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function refresh(preferred?: string) {
    setLoading(true);
    try {
      const rows = await listManagedMcpServers();
      setServers(rows);
      setSelected((current) => {
        const next = preferred || current;
        return rows.some((row) => row.name === next)
          ? next
          : rows[0]?.name || null;
      });
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "服务加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    return () => {
      if (hideSecretsTimer.current) clearTimeout(hideSecretsTimer.current);
    };
  }, []);

  useEffect(() => {
    setRevealed({});
    if (hideSecretsTimer.current) clearTimeout(hideSecretsTimer.current);
  }, [selected]);

  const visibleServers = useMemo(
    () =>
      servers.filter(
        (server) => filter === "all" || server.category === filter,
      ),
    [filter, servers],
  );
  const current = servers.find((server) => server.name === selected) || null;

  useEffect(() => {
    if (
      current &&
      (filter === "all" || current.category === filter)
    ) {
      return;
    }
    setSelected(visibleServers[0]?.name || null);
  }, [current, filter, visibleServers]);

  async function toggle(server: ManagedMcpServer) {
    const enabled = !server.enabled;
    if (
      server.category === "system" &&
      !enabled &&
      !window.confirm("停用后，报告创建和编辑能力将不可用。确定继续吗？")
    ) {
      return;
    }
    setMessage("正在应用...");
    try {
      const updated = await updateMcpServerEnabled(server.name, enabled);
      setServers((rows) =>
        rows.map((row) => (row.name === updated.name ? updated : row)),
      );
      setMessage(enabled ? "服务已启用" : "服务已停用");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "更新失败");
    }
  }

  async function test(server: ManagedMcpServer) {
    setTests((rows) => ({
      ...rows,
      [server.name]: { ok: false, status: "testing", message: "正在连接并发现工具..." },
    }));
    try {
      const result = await testManagedMcpServer(server.name);
      setTests((rows) => ({ ...rows, [server.name]: result }));
      await refresh(server.name);
    } catch (error) {
      setTests((rows) => ({
        ...rows,
        [server.name]: {
          ok: false,
          status: "failed",
          message: error instanceof Error ? error.message : "检查失败",
        },
      }));
    }
  }

  async function reveal(server: ManagedMcpServer) {
    try {
      const secrets = await revealManagedMcpSecrets(server.name);
      setRevealed(secrets);
      if (hideSecretsTimer.current) clearTimeout(hideSecretsTimer.current);
      hideSecretsTimer.current = setTimeout(() => setRevealed({}), 30_000);
      setMessage("密钥已显示，将在 30 秒后自动隐藏");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "密钥读取失败");
    }
  }

  async function remove(server: ManagedMcpServer) {
    if (!window.confirm(`删除外部 MCP“${server.displayName}”？此操作不可撤销。`)) return;
    try {
      await deleteManagedMcpServer(server.name);
      await refresh();
      setMessage("外部 MCP 已删除");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    }
  }

  async function save(input: ManagedMcpInput) {
    const saved =
      editor?.mode === "edit" && editor.server
        ? await updateManagedMcpServer(editor.server.name, input)
        : await createManagedMcpServer(input);
    setEditor(null);
    await refresh(saved.name);
    setMessage(editor?.mode === "edit" ? "MCP 配置已保存" : "MCP 已添加");
  }

  function duplicate(server: ManagedMcpServer) {
    setEditor({
      mode: "create",
      server: {
        ...server,
        name: `${server.name}_copy`,
        displayName: `${server.displayName} 副本`,
        environment: server.environment.map((item) => ({
          ...item,
          value: item.secret ? "" : item.value,
        })),
      },
    });
  }

  return (
    <div className="system-domain-panel system-mcp-panel">
      <div className="system-section-heading">
        <div><span>CONNECTIONS</span><h2>MCP 服务</h2></div>
        <div className="system-heading-actions">
          <p>系统能力由代码维护；外部能力由管理员统一接入。</p>
          <button type="button" onClick={() => setEditor({ mode: "create" })}>
            <span aria-hidden="true">＋</span> 添加 MCP
          </button>
        </div>
      </div>

      <div className="system-mcp-summary">
        <div className="system-mcp-filters" aria-label="MCP 分类">
          {([
            ["all", "全部"],
            ["system", "系统内置"],
            ["external", "外部接入"],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={filter === value ? "active" : ""}
              onClick={() => setFilter(value)}
            >
              {label}
              <span>
                {value === "all"
                  ? servers.length
                  : servers.filter((server) => server.category === value).length}
              </span>
            </button>
          ))}
        </div>
        <div className="system-mcp-health">
          <span><i className="online" />{servers.filter((item) => item.enabled).length} 个已启用</span>
          <button type="button" onClick={() => void refresh()}>刷新</button>
        </div>
      </div>

      <div className="system-master-detail system-mcp-master-detail">
        <div className="system-master-list">
          <header><strong>服务清单</strong><span>{visibleServers.length}</span></header>
          {visibleServers.map((server) => (
            <button
              type="button"
              key={server.name}
              className={selected === server.name ? "active" : ""}
              onClick={() => setSelected(server.name)}
            >
              <span className={`system-server-monogram ${server.category}`}>
                {server.category === "system" ? "S" : "M"}
              </span>
              <span>
                <strong>{server.displayName || server.name}</strong>
                <small>{server.name} · {server.tools.length} 个工具</small>
              </span>
              <i className={server.enabled ? "online" : ""} />
            </button>
          ))}
          {!loading && visibleServers.length === 0 && <p className="system-empty">暂无服务</p>}
        </div>

        <div className="system-detail-card">
          {current ? (
            <>
              <header>
                <div>
                  <span>{current.category === "system" ? "系统内置" : "外部接入"}</span>
                  <h3>{current.displayName || current.name}</h3>
                  <code>{current.name}</code>
                </div>
                <div className="system-detail-actions">
                  {current.mutable && (
                    <>
                      <button type="button" onClick={() => setEditor({ mode: "edit", server: current })}>编辑</button>
                      <button type="button" onClick={() => duplicate(current)}>复制</button>
                      <button className="danger" type="button" onClick={() => void remove(current)}>删除</button>
                    </>
                  )}
                  <button
                    className={`system-switch ${current.enabled ? "on" : ""}`}
                    type="button"
                    aria-label={`${current.enabled ? "停用" : "启用"} ${current.name}`}
                    onClick={() => void toggle(current)}
                  ><span /></button>
                </div>
              </header>

              {current.category === "system" && (
                <div className="system-mcp-built-in-note">
                  配置由系统代码维护，管理员可检查工具和控制启停，但不能编辑或删除。
                </div>
              )}

              <div className="system-badge-row">
                <span>{current.transport === "stdio" ? "stdio" : "Streamable HTTP"}</span>
                <span>{current.status}</span>
                <span>{current.permission}</span>
                <span>{current.approval === "trusted" ? "受信任" : "按策略审批"}</span>
              </div>

              <dl className="system-definition-list">
                <div>
                  <dt>{current.transport === "stdio" ? "启动命令" : "服务地址"}</dt>
                  <dd>
                    {current.transport === "stdio"
                      ? `${current.command} ${current.args.join(" ")}`.trim()
                      : current.url}
                  </dd>
                </div>
                <div><dt>环境变量</dt><dd>{current.envKeys.join(" · ") || "无"}</dd></div>
              </dl>

              {current.category === "external" && current.envKeys.length > 0 && (
                <section className="system-secret-list">
                  <header>
                    <strong>密钥与变量</strong>
                    <div>
                      <button type="button" onClick={() => void reveal(current)}>
                        {Object.keys(revealed).length ? "重新计时" : "查看密钥"}
                      </button>
                      {Object.keys(revealed).length > 0 && (
                        <button type="button" onClick={() => setRevealed({})}>隐藏</button>
                      )}
                    </div>
                  </header>
                  {current.envKeys.map((key) => {
                    const value =
                      revealed[key] ??
                      current.environment.find((item) => item.key === key)?.value ??
                      "••••••••";
                    return (
                      <div key={key}>
                        <code>{key}</code>
                        <span>{value}</span>
                        {revealed[key] && (
                          <button
                            type="button"
                            onClick={() => void navigator.clipboard?.writeText(revealed[key])}
                          >复制</button>
                        )}
                      </div>
                    );
                  })}
                </section>
              )}

              <section className="system-tool-list">
                <header><strong>已发现工具</strong><span>{current.tools.length}</span></header>
                {current.tools.map((tool) => (
                  <div key={tool.name}>
                    <span><strong>{tool.name}</strong><small>{tool.description}</small></span>
                    <em>{tool.permission}</em>
                  </div>
                ))}
                {current.tools.length === 0 && (
                  <div className="system-empty">运行检查后显示服务提供的工具</div>
                )}
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
      {editor && (
        <McpEditor
          mode={editor.mode}
          server={editor.server}
          onClose={() => setEditor(null)}
          onSave={save}
        />
      )}
    </div>
  );
}

function McpEditor({
  mode,
  server,
  onClose,
  onSave,
}: {
  mode: "create" | "edit";
  server?: ManagedMcpServer;
  onClose: () => void;
  onSave: (input: ManagedMcpInput) => Promise<void>;
}) {
  const [input, setInput] = useState<ManagedMcpInput>(() => ({
    ...emptyInput,
    ...(server
      ? {
          name: server.name,
          displayName: server.displayName,
          transport: server.transport,
          command: server.command,
          args: server.args,
          url: server.url,
          bearerTokenEnvVar: server.bearerTokenEnvVar,
          oauthClientId: server.oauthClientId,
          oauthResource: server.oauthResource,
          environment: server.environment.map((item) => ({
            ...item,
            value: item.secret ? "" : item.value,
          })),
          enabled: server.enabled,
        }
      : {}),
  }));
  const [argsText, setArgsText] = useState((server?.args || []).join("\n"));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function change<K extends keyof ManagedMcpInput>(
    key: K,
    value: ManagedMcpInput[K],
  ) {
    setInput((current) => ({ ...current, [key]: value }));
  }

  function updateEnvironment(index: number, patch: Partial<ManagedMcpEnvironment>) {
    change(
      "environment",
      input.environment.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave({
        ...input,
        args: argsText.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="system-mcp-editor-backdrop" role="presentation">
      <section className="system-mcp-editor" role="dialog" aria-modal="true" aria-labelledby="mcp-editor-title">
        <header>
          <div>
            <span>EXTERNAL CONNECTION</span>
            <h3 id="mcp-editor-title">{mode === "create" ? "添加 MCP 服务" : "编辑 MCP 服务"}</h3>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose}>×</button>
        </header>
        <form onSubmit={(event) => void submit(event)}>
          <div className="system-mcp-form-grid">
            <label>
              <span>服务名称</span>
              <input
                required
                disabled={mode === "edit"}
                value={input.name}
                onChange={(event) => change("name", event.target.value)}
                placeholder="例如 BI_doris"
              />
              <small>{mode === "edit" ? "创建后不可修改" : "仅支持字母、数字、下划线和短横线"}</small>
            </label>
            <label>
              <span>显示名称</span>
              <input
                value={input.displayName}
                onChange={(event) => change("displayName", event.target.value)}
                placeholder="例如 Doris 查询"
              />
            </label>
          </div>

          <fieldset className="system-transport-picker">
            <legend>传输方式</legend>
            <button
              type="button"
              className={input.transport === "stdio" ? "active" : ""}
              onClick={() => change("transport", "stdio")}
            >
              <strong>stdio</strong><small>本地命令或包进程</small>
            </button>
            <button
              type="button"
              className={input.transport === "streamable_http" ? "active" : ""}
              onClick={() => change("transport", "streamable_http")}
            >
              <strong>Streamable HTTP</strong><small>远程 MCP 服务地址</small>
            </button>
          </fieldset>

          {input.transport === "stdio" ? (
            <div className="system-mcp-form-grid">
              <label>
                <span>启动命令</span>
                <input required value={input.command} onChange={(event) => change("command", event.target.value)} placeholder="npx" />
              </label>
              <label>
                <span>参数（每行一个）</span>
                <textarea value={argsText} onChange={(event) => setArgsText(event.target.value)} placeholder={"-y\n@scope/mcp-server"} />
              </label>
            </div>
          ) : (
            <>
              <label>
                <span>服务 URL</span>
                <input required type="url" value={input.url} onChange={(event) => change("url", event.target.value)} placeholder="https://example.com/mcp" />
              </label>
              <div className="system-mcp-form-grid">
                <label>
                  <span>Bearer Token 环境变量名</span>
                  <input value={input.bearerTokenEnvVar} onChange={(event) => change("bearerTokenEnvVar", event.target.value)} placeholder="EXTERNAL_MCP_TOKEN" />
                </label>
                <label>
                  <span>Bearer Token</span>
                  <input type="password" value={input.bearerToken || ""} onChange={(event) => change("bearerToken", event.target.value)} placeholder={mode === "edit" ? "留空保留原值" : "输入明文，入库自动加密"} />
                </label>
                <label>
                  <span>OAuth Client ID</span>
                  <input value={input.oauthClientId} onChange={(event) => change("oauthClientId", event.target.value)} />
                </label>
                <label>
                  <span>OAuth Resource</span>
                  <input value={input.oauthResource} onChange={(event) => change("oauthResource", event.target.value)} />
                </label>
              </div>
            </>
          )}

          <section className="system-environment-editor">
            <header>
              <div><strong>环境变量</strong><small>敏感项以明文录入，保存时加密</small></div>
              <button
                type="button"
                onClick={() => change("environment", [...input.environment, { key: "", value: "", secret: false }])}
              >＋ 添加变量</button>
            </header>
            {input.environment.map((item, index) => (
              <div key={`${index}-${item.key}`}>
                <input aria-label={`变量名 ${index + 1}`} value={item.key} onChange={(event) => updateEnvironment(index, { key: event.target.value })} placeholder="变量名" />
                <input aria-label={`变量值 ${index + 1}`} type={item.secret ? "password" : "text"} value={item.value} onChange={(event) => updateEnvironment(index, { value: event.target.value })} placeholder={item.secret && mode === "edit" ? "留空保留原值" : "变量值"} />
                <label><input type="checkbox" checked={item.secret} onChange={(event) => updateEnvironment(index, { secret: event.target.checked })} /> 密钥</label>
                <button type="button" aria-label={`删除变量 ${index + 1}`} onClick={() => change("environment", input.environment.filter((_, itemIndex) => itemIndex !== index))}>×</button>
              </div>
            ))}
          </section>

          {error && <p className="system-form-error">{error}</p>}
          <footer>
            <button type="button" onClick={onClose}>取消</button>
            <button className="primary" type="submit" disabled={saving}>{saving ? "保存中..." : "保存配置"}</button>
          </footer>
        </form>
      </section>
    </div>
  );
}
