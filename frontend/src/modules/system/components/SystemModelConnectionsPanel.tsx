"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import {
  createManagedModelConnection,
  deleteManagedModelConnection,
  listManagedModelConnections,
  revealManagedModelConnectionSecret,
  setDefaultManagedModelConnection,
  testManagedModelConnection,
  updateManagedModelConnection,
  type ManagedModelConnection,
  type ManagedModelConnectionInput,
  type ManagedModelProviderType,
} from "../system-api";

type EditorState = {
  mode: "create" | "edit";
  connection?: ManagedModelConnection;
} | null;

type TestResult = {
  ok: boolean;
  status: string;
  message: string;
  latencyMs?: number;
};

const providerOptions: Array<{
  value: ManagedModelProviderType;
  label: string;
  note: string;
  baseUrl: string;
}> = [
  {
    value: "openai",
    label: "OpenAI",
    note: "官方模型服务",
    baseUrl: "https://api.openai.com/v1",
  },
  {
    value: "minimax",
    label: "MiniMax",
    note: "兼容适配服务",
    baseUrl: "https://api.minimaxi.com/v1",
  },
  {
    value: "openai_compatible",
    label: "OpenAI-compatible",
    note: "其他兼容服务",
    baseUrl: "",
  },
];

const emptyInput: ManagedModelConnectionInput = {
  name: "",
  displayName: "",
  providerType: "openai",
  model: "",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  enabled: true,
};

export function SystemModelConnectionsPanel() {
  const [connections, setConnections] = useState<ManagedModelConnection[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [editor, setEditor] = useState<EditorState>(null);
  const [revealedApiKey, setRevealedApiKey] = useState("");
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const hideSecretTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function refresh(preferred?: string) {
    setLoading(true);
    try {
      const rows = await listManagedModelConnections();
      setConnections(rows);
      setSelected((current) => {
        const next = preferred || current;
        return rows.some((row) => row.name === next)
          ? next
          : rows.find((row) => row.isDefault)?.name || rows[0]?.name || null;
      });
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "模型连接加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    return () => {
      if (hideSecretTimer.current) clearTimeout(hideSecretTimer.current);
    };
  }, []);

  useEffect(() => {
    setRevealedApiKey("");
    if (hideSecretTimer.current) clearTimeout(hideSecretTimer.current);
  }, [selected]);

  const current =
    connections.find((connection) => connection.name === selected) || null;

  async function toggle(connection: ManagedModelConnection) {
    if (connection.isDefault) {
      setMessage("请先选择另一个默认连接，再停用当前连接");
      return;
    }
    try {
      const updated = await updateManagedModelConnection(connection.name, {
        enabled: !connection.enabled,
      });
      setConnections((rows) =>
        rows.map((row) => (row.name === updated.name ? updated : row)),
      );
      setMessage(updated.enabled ? "连接已启用" : "连接已停用");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "更新失败");
    }
  }

  async function makeDefault(connection: ManagedModelConnection) {
    setMessage("正在切换默认连接...");
    try {
      const updated = await setDefaultManagedModelConnection(connection.name);
      setConnections((rows) =>
        rows.map((row) =>
          row.name === updated.name
            ? { ...updated, isDefault: true }
            : { ...row, isDefault: false },
        ),
      );
      setMessage("默认连接已更新，将用于后续分析");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "默认连接更新失败");
    }
  }

  async function testConnection(connection: ManagedModelConnection) {
    setTests((rows) => ({
      ...rows,
      [connection.name]: {
        ok: false,
        status: "testing",
        message: "正在验证模型服务...",
      },
    }));
    try {
      const result = await testManagedModelConnection(connection.name);
      setTests((rows) => ({ ...rows, [connection.name]: result }));
      setConnections((rows) =>
        rows.map((row) =>
          row.name === connection.name
            ? { ...row, status: result.status, message: result.message }
            : row,
        ),
      );
    } catch (error) {
      setTests((rows) => ({
        ...rows,
        [connection.name]: {
          ok: false,
          status: "failed",
          message: error instanceof Error ? error.message : "连接检查失败",
        },
      }));
    }
  }

  async function reveal(connection: ManagedModelConnection) {
    try {
      const apiKey = await revealManagedModelConnectionSecret(connection.name);
      setRevealedApiKey(apiKey);
      if (hideSecretTimer.current) clearTimeout(hideSecretTimer.current);
      hideSecretTimer.current = setTimeout(() => setRevealedApiKey(""), 30_000);
      setMessage("密钥已显示，将在 30 秒后自动隐藏");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "密钥读取失败");
    }
  }

  async function remove(connection: ManagedModelConnection) {
    if (connection.isDefault) {
      setMessage("请先选择另一个默认连接，再删除当前连接");
      return;
    }
    if (!window.confirm(`删除模型连接“${connection.displayName}”？此操作不可撤销。`)) {
      return;
    }
    try {
      await deleteManagedModelConnection(connection.name);
      await refresh();
      setMessage("模型连接已删除");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    }
  }

  async function save(input: ManagedModelConnectionInput) {
    const saved =
      editor?.mode === "edit" && editor.connection
        ? await updateManagedModelConnection(editor.connection.name, input)
        : await createManagedModelConnection(input);
    setEditor(null);
    await refresh(saved.name);
    setMessage(editor?.mode === "edit" ? "模型连接已保存" : "模型连接已添加");
  }

  const enabledCount = connections.filter((connection) => connection.enabled).length;
  const defaultConnection = connections.find((connection) => connection.isDefault);

  return (
    <div className="system-domain-panel system-model-connections-panel">
      <div className="system-section-heading">
        <div>
          <span>MODEL CONNECTIONS</span>
          <h2>模型连接</h2>
        </div>
        <div className="system-heading-actions">
          <p>统一维护分析运行使用的模型服务。</p>
          <button type="button" onClick={() => setEditor({ mode: "create" })}>
            <span aria-hidden="true">＋</span> 添加连接
          </button>
        </div>
      </div>

      <div className="system-mcp-summary system-model-summary">
        <div className="system-mcp-health">
          <span><i className="online" />{enabledCount} 个已启用</span>
          <span>默认：{defaultConnection?.displayName || "未设置"}</span>
        </div>
        <div className="system-mcp-health">
          <span>固定使用 Responses API</span>
          <button type="button" onClick={() => void refresh()}>刷新</button>
        </div>
      </div>

      <div className="system-master-detail system-model-master-detail">
        <div className="system-master-list">
          <header><strong>连接清单</strong><span>{connections.length}</span></header>
          {connections.map((connection) => (
            <button
              type="button"
              key={connection.name}
              className={selected === connection.name ? "active" : ""}
              onClick={() => setSelected(connection.name)}
            >
              <span className={`system-server-monogram ${connection.providerType}`}>
                {providerMonogram(connection.providerType)}
              </span>
              <span>
                <strong>{connection.displayName || connection.name}</strong>
                <small>
                  {providerLabel(connection.providerType)} · {connection.model}
                  {connection.isDefault ? " · 默认" : ""}
                </small>
              </span>
              <i className={connection.enabled ? "online" : ""} />
            </button>
          ))}
          {!loading && connections.length === 0 && (
            <p className="system-empty">暂无连接</p>
          )}
        </div>

        <div className="system-detail-card system-model-detail-card">
          {current ? (
            <>
              <header>
                <div>
                  <span>{providerLabel(current.providerType)}</span>
                  <h3>{current.displayName || current.name}</h3>
                  <code>{current.name}</code>
                </div>
                <div className="system-detail-actions">
                  {!current.isDefault && current.enabled && (
                    <button
                      type="button"
                      onClick={() => void makeDefault(current)}
                    >
                      设为默认
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      setEditor({ mode: "edit", connection: current })
                    }
                  >
                    编辑
                  </button>
                  <button
                    className="danger"
                    type="button"
                    disabled={current.isDefault}
                    title={current.isDefault ? "请先切换默认连接" : undefined}
                    onClick={() => void remove(current)}
                  >
                    删除
                  </button>
                  <button
                    className={`system-switch ${current.enabled ? "on" : ""}`}
                    type="button"
                    disabled={current.isDefault}
                    title={current.isDefault ? "请先切换默认连接" : undefined}
                    aria-label={`${current.enabled ? "停用" : "启用"} ${current.name}`}
                    onClick={() => void toggle(current)}
                  >
                    <span />
                  </button>
                </div>
              </header>

              {current.isDefault && (
                <div className="system-model-default-note">
                  当前默认连接不能停用或删除；切换默认连接后即可操作。
                </div>
              )}

              <div className="system-badge-row">
                {current.isDefault && <span className="default">当前默认</span>}
                <span>{current.enabled ? "已启用" : "已停用"}</span>
                <span>{providerLabel(current.providerType)}</span>
                <span>Responses API</span>
                <span>{statusLabel(current.status)}</span>
              </div>

              <dl className="system-definition-list">
                <div><dt>模型</dt><dd>{current.model}</dd></div>
                <div><dt>API Base URL</dt><dd>{current.baseUrl}</dd></div>
                <div>
                  <dt>最近检查</dt>
                  <dd>{formatTestedAt(current.lastTestedAt)}</dd>
                </div>
              </dl>

              <section className="system-secret-list system-model-secret">
                <header>
                  <strong>API Key</strong>
                  <div>
                    <button type="button" onClick={() => void reveal(current)}>
                      {revealedApiKey ? "重新计时" : "查看密钥"}
                    </button>
                    {revealedApiKey && (
                      <button type="button" onClick={() => setRevealedApiKey("")}>
                        隐藏
                      </button>
                    )}
                  </div>
                </header>
                <div>
                  <code>API_KEY</code>
                  <span>{revealedApiKey || "••••••••"}</span>
                  {revealedApiKey ? (
                    <button
                      type="button"
                      onClick={() =>
                        void navigator.clipboard?.writeText(revealedApiKey)
                      }
                    >
                      复制
                    </button>
                  ) : <span />}
                </div>
              </section>

              <footer>
                <button type="button" onClick={() => void testConnection(current)}>
                  运行检查
                </button>
                <p className={tests[current.name]?.ok ? "ok" : ""}>
                  {testMessage(tests[current.name]) || current.message}
                </p>
              </footer>
            </>
          ) : loading ? (
            <div className="system-empty">正在读取模型连接...</div>
          ) : (
            <div className="system-model-empty">
              <span aria-hidden="true">M</span>
              <strong>还没有模型连接</strong>
              <p>添加第一个连接后，系统会自动将它设为默认连接。</p>
              <button type="button" onClick={() => setEditor({ mode: "create" })}>
                添加第一个连接
              </button>
            </div>
          )}
        </div>
      </div>

      {message && <p className="system-inline-message" role="status">{message}</p>}
      {editor && (
        <ModelConnectionEditor
          mode={editor.mode}
          connection={editor.connection}
          onClose={() => setEditor(null)}
          onSave={save}
        />
      )}
    </div>
  );
}

function ModelConnectionEditor({
  mode,
  connection,
  onClose,
  onSave,
}: {
  mode: "create" | "edit";
  connection?: ManagedModelConnection;
  onClose: () => void;
  onSave: (input: ManagedModelConnectionInput) => Promise<void>;
}) {
  const [input, setInput] = useState<ManagedModelConnectionInput>(() => ({
    ...emptyInput,
    ...(connection
      ? {
          name: connection.name,
          displayName: connection.displayName,
          providerType: connection.providerType,
          model: connection.model,
          baseUrl: connection.baseUrl,
          apiKey: "",
          enabled: connection.enabled,
        }
      : {}),
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function change<K extends keyof ManagedModelConnectionInput>(
    key: K,
    value: ManagedModelConnectionInput[K],
  ) {
    setInput((current) => ({ ...current, [key]: value }));
  }

  function chooseProvider(providerType: ManagedModelProviderType) {
    const option = providerOptions.find((item) => item.value === providerType);
    setInput((current) => ({
      ...current,
      providerType,
      baseUrl: option?.baseUrl || current.baseUrl,
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave(input);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="system-model-editor-backdrop" role="presentation">
      <section
        className="system-model-editor"
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-editor-title"
      >
        <header>
          <div>
            <span>MODEL CONNECTION</span>
            <h3 id="model-editor-title">
              {mode === "create" ? "添加模型连接" : "编辑模型连接"}
            </h3>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose}>×</button>
        </header>
        <form onSubmit={(event) => void submit(event)}>
          <div className="system-mcp-form-grid">
            <label>
              <span>连接名称</span>
              <input
                aria-label="连接名称"
                required
                disabled={mode === "edit"}
                value={input.name}
                onChange={(event) => change("name", event.target.value)}
                placeholder="例如 minimax_main"
              />
              <small>
                {mode === "edit"
                  ? "创建后不可修改"
                  : "仅支持字母、数字、下划线和短横线"}
              </small>
            </label>
            <label>
              <span>显示名称</span>
              <input
                aria-label="显示名称"
                value={input.displayName}
                onChange={(event) => change("displayName", event.target.value)}
                placeholder="例如 MiniMax 主连接"
              />
            </label>
          </div>

          <fieldset className="system-transport-picker system-model-provider-picker">
            <legend>提供方</legend>
            {providerOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-label={option.label}
                className={input.providerType === option.value ? "active" : ""}
                onClick={() => chooseProvider(option.value)}
              >
                <strong>{option.label}</strong>
                <small>{option.note}</small>
              </button>
            ))}
          </fieldset>

          <div className="system-mcp-form-grid">
            <label>
              <span>模型名称</span>
              <input
                aria-label="模型名称"
                required
                value={input.model}
                onChange={(event) => change("model", event.target.value)}
                placeholder="例如 MiniMax-M3"
              />
            </label>
            <label>
              <span>API Base URL</span>
              <input
                aria-label="API Base URL"
                required
                type="url"
                value={input.baseUrl}
                onChange={(event) => change("baseUrl", event.target.value)}
                placeholder="https://models.example.com/v1"
              />
            </label>
          </div>

          <label>
            <span>API Key</span>
            <input
              aria-label="API Key"
              required={mode === "create"}
              type="password"
              value={input.apiKey || ""}
              onChange={(event) => change("apiKey", event.target.value)}
              placeholder={mode === "edit" ? "留空保留原值" : "输入明文，入库自动加密"}
              autoComplete="new-password"
            />
            <small>网页以明文录入，保存后由服务端加密。</small>
          </label>

          <aside className="system-model-protocol-note">
            <strong>Responses API</strong>
            <p>所有模型连接固定使用统一响应协议。</p>
          </aside>

          {error && <p className="system-form-error">{error}</p>}
          <footer>
            <button type="button" onClick={onClose}>取消</button>
            <button className="primary" type="submit" disabled={saving}>
              {saving ? "保存中..." : "保存连接"}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}

function providerLabel(providerType: ManagedModelProviderType): string {
  return providerOptions.find((option) => option.value === providerType)?.label
    || providerType;
}

function providerMonogram(providerType: ManagedModelProviderType): string {
  if (providerType === "minimax") return "M";
  if (providerType === "openai") return "O";
  return "C";
}

function statusLabel(status: string): string {
  if (status === "ready") return "连接可用";
  if (status === "failed") return "检查失败";
  if (status === "disabled") return "已停用";
  return "尚未检查";
}

function formatTestedAt(value: string | null): string {
  if (!value) return "尚未检查";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", { hour12: false });
}

function testMessage(result: TestResult | undefined): string {
  if (!result) return "";
  return result.latencyMs === undefined
    ? result.message
    : `${result.message} · ${result.latencyMs} ms`;
}
