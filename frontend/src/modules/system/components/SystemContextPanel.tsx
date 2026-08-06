"use client";

import { useEffect, useState } from "react";

import {
  getManagedContext,
  saveManagedContext,
  type ManagedContext,
} from "../system-api";

type ContextSection =
  | "overview"
  | "base"
  | "system"
  | "runtime"
  | "skills"
  | "mcp";

const contextSections: Array<{
  id: ContextSection;
  label: string;
  note: string;
}> = [
  { id: "overview", label: "上下文总览", note: "注入顺序与当前状态" },
  { id: "base", label: "内置基础指令", note: "可修改" },
  { id: "system", label: "系统提示词", note: "可修改" },
  { id: "runtime", label: "权限与环境", note: "只读" },
  { id: "skills", label: "Skills 上下文", note: "只读" },
  { id: "mcp", label: "MCP 工具上下文", note: "只读" },
];

export function SystemContextPanel() {
  const [context, setContext] = useState<ManagedContext | null>(null);
  const [section, setSection] = useState<ContextSection>("overview");
  const [baseInstructions, setBaseInstructions] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    void getManagedContext()
      .then((result) => {
        if (!active) return;
        setContext(result);
        setBaseInstructions(result.baseInstructions.content);
        setSystemPrompt(result.systemPrompt.content);
      })
      .catch((error) => {
        if (active) {
          setMessage(error instanceof Error ? error.message : "上下文读取失败");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function saveInstruction(kind: "base" | "system") {
    const content = kind === "base" ? baseInstructions : systemPrompt;
    if (!content.trim()) {
      setMessage("内容不能为空");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const next = await saveManagedContext(
        kind === "base"
          ? { baseInstructions: content }
          : { systemPrompt: content },
      );
      setContext(next);
      setBaseInstructions(next.baseInstructions.content);
      setSystemPrompt(next.systemPrompt.content);
      setMessage(kind === "base" ? "基础指令已保存" : "系统提示词已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="system-context">
      <div className="system-section-heading">
        <div>
          <span>CONTEXT CONTROL</span>
          <h2>上下文管理</h2>
        </div>
        <p>统一查看 Agent 每次运行时使用的指令、权限、Skills 与 MCP 工具。</p>
      </div>

      <nav className="system-context-nav" aria-label="上下文分类">
        {contextSections.map((item, index) => (
          <button
            className={section === item.id ? "active" : ""}
            key={item.id}
            type="button"
            onClick={() => {
              setSection(item.id);
              setMessage("");
            }}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{item.label}</strong>
            <small>{item.note}</small>
          </button>
        ))}
      </nav>

      {!context ? (
        <div className="system-context-loading">
          <span className="system-loader" />
          <p>{message || "正在读取当前上下文"}</p>
        </div>
      ) : (
        <div className="system-context-body">
          {section === "overview" && <ContextOverview context={context} />}
          {section === "base" && (
            <InstructionEditor
              eyebrow="BASE INSTRUCTIONS"
              title="内置基础指令"
              description={
                context.baseInstructions.source === "managed"
                  ? "当前使用管理员维护的基础指令。保存后，后续 Agent 运行直接使用新内容。"
                  : "当前继续使用运行环境提供的原生基础指令。输入完整内容并保存后，将由这里的内容替代。"
              }
              label="基础指令内容"
              value={baseInstructions}
              onChange={setBaseInstructions}
              onSave={() => void saveInstruction("base")}
              saving={saving}
              saveLabel="保存基础指令"
              status={
                context.baseInstructions.source === "managed"
                  ? "已配置"
                  : "使用原生指令"
              }
            />
          )}
          {section === "system" && (
            <InstructionEditor
              eyebrow="SYSTEM PROMPT"
              title="系统提示词"
              description="用于约束 GenBI 的业务分析方式、数据可信要求和报告生成行为。"
              label="系统提示词内容"
              value={systemPrompt}
              onChange={setSystemPrompt}
              onSave={() => void saveInstruction("system")}
              saving={saving}
              saveLabel="保存系统提示词"
              status="已启用"
            />
          )}
          {section === "runtime" && <RuntimeContext context={context} />}
          {section === "skills" && <SkillsContext context={context} />}
          {section === "mcp" && <McpContext context={context} />}
        </div>
      )}
      {message && context && (
        <p className="system-context-message" role="status">{message}</p>
      )}
    </div>
  );
}

function ContextOverview({ context }: { context: ManagedContext }) {
  const rows = [
    {
      index: "01",
      name: "内置基础指令",
      value:
        context.baseInstructions.source === "managed"
          ? "管理员配置"
          : "运行环境原生指令",
      mode: "可修改",
    },
    {
      index: "02",
      name: "系统提示词",
      value: context.systemPrompt.content ? "已配置" : "未配置",
      mode: "可修改",
    },
    {
      index: "03",
      name: "权限与环境",
      value: `${context.runtime.provider} · ${context.runtime.model || "默认模型"}`,
      mode: "只读",
    },
    {
      index: "04",
      name: "Skills 上下文",
      value: `${context.skills.length} 项能力`,
      mode: "只读",
    },
    {
      index: "05",
      name: "MCP 工具上下文",
      value: `${context.mcpServers.length} 个服务`,
      mode: "只读",
    },
  ];
  return (
    <section className="system-context-overview" aria-label="上下文总览">
      <header>
        <div>
          <span>ACTIVE CONTEXT</span>
          <h3>当前上下文组成</h3>
        </div>
        <p>下列内容共同决定 Agent 的身份、行为边界和可调用能力。</p>
      </header>
      <div>
        {rows.map((row) => (
          <article key={row.index}>
            <span>{row.index}</span>
            <strong>{row.name}</strong>
            <p>{row.value}</p>
            <em>{row.mode}</em>
          </article>
        ))}
      </div>
    </section>
  );
}

function InstructionEditor({
  eyebrow,
  title,
  description,
  label,
  value,
  onChange,
  onSave,
  saving,
  saveLabel,
  status,
}: {
  eyebrow: string;
  title: string;
  description: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  saving: boolean;
  saveLabel: string;
  status: string;
}) {
  return (
    <section className="system-context-editor">
      <header>
        <div>
          <span>{eyebrow}</span>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <em>{status}</em>
      </header>
      <label>
        <span>{label}</span>
        <textarea
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="输入完整指令内容"
          spellCheck={false}
        />
      </label>
      <footer>
        <small>直接保存，无草稿、发布或版本切换流程。</small>
        <button type="button" disabled={saving} onClick={onSave}>
          {saving ? "正在保存…" : saveLabel}
        </button>
      </footer>
    </section>
  );
}

function RuntimeContext({ context }: { context: ManagedContext }) {
  const items = [
    ["运行状态", context.runtime.enabled ? "运行中" : "未启用"],
    ["Provider", context.runtime.provider],
    ["Model", context.runtime.model || "默认模型"],
    ["Approval", context.runtime.approvalMode],
    ["Sandbox", context.runtime.sandbox],
    [
      "Default tools",
      context.runtime.defaultToolsEnabled ? "Enabled" : "Disabled",
    ],
  ];
  return (
    <ReadOnlySection
      eyebrow="PERMISSIONS / RUNTIME"
      title="权限与运行环境"
      description="这里只展示当前生效状态，修改仍由对应的系统能力负责。"
    >
      <div className="system-context-runtime">
        {items.map(([label, value]) => (
          <article key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </div>
    </ReadOnlySection>
  );
}

function SkillsContext({ context }: { context: ManagedContext }) {
  return (
    <ReadOnlySection
      eyebrow="SKILLS"
      title="Skills 上下文"
      description="展示运行环境中可被识别的能力说明，不展示 Skill 文件正文。"
    >
      <div className="system-context-list">
        {context.skills.map((skill, index) => (
          <article key={`${skill.scope}:${skill.name}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{skill.name}</strong>
              <p>{skill.description || "暂无说明"}</p>
            </div>
            <em>{skill.scope === "system" ? "系统" : "用户"}</em>
          </article>
        ))}
        {!context.skills.length && <p className="system-context-empty">暂无 Skills</p>}
      </div>
    </ReadOnlySection>
  );
}

function McpContext({ context }: { context: ManagedContext }) {
  return (
    <ReadOnlySection
      eyebrow="MCP TOOLS"
      title="MCP 工具上下文"
      description="展示 Agent 可见的 MCP 服务和工具；密钥与环境变量值不会出现在这里。"
    >
      <div className="system-context-mcp">
        {context.mcpServers.map((server) => (
          <article key={server.name}>
            <header>
              <div>
                <strong>{server.displayName || server.name}</strong>
                <span>{server.name}</span>
              </div>
              <em className={server.enabled ? "online" : ""}>
                {server.enabled ? "已启用" : "已停用"}
              </em>
            </header>
            <div>
              {server.tools.map((tool) => (
                <p key={tool.name}>
                  <strong>{tool.name}</strong>
                  <span>{tool.description || "暂无说明"}</span>
                </p>
              ))}
              {!server.tools.length && <p><span>尚未读取工具列表</span></p>}
            </div>
          </article>
        ))}
      </div>
    </ReadOnlySection>
  );
}

function ReadOnlySection({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="system-context-readonly">
      <header>
        <div>
          <span>{eyebrow}</span>
          <h3>{title}</h3>
        </div>
        <p>{description}</p>
        <em>只读</em>
      </header>
      {children}
    </section>
  );
}
