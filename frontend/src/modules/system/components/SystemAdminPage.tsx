"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";

import {
  bootstrapSystemAdministrator,
  getSystemAccess,
  type SystemAccess,
} from "../system-api";
import { SystemMcpPanel } from "./SystemMcpPanel";
import { SystemPromptsPanel } from "./SystemPromptsPanel";
import { SystemRuntimePanel } from "./SystemRuntimePanel";
import { SystemUsersPanel } from "./SystemUsersPanel";

export type SystemSection = "overview" | "users" | "mcp" | "prompts" | "runtime";

export const systemSections: Array<{
  id: SystemSection;
  label: string;
  description: string;
}> = [
  { id: "overview", label: "系统总览", description: "配置与运行状态" },
  { id: "users", label: "用户与权限", description: "账号、角色和状态" },
  { id: "mcp", label: "MCP 服务", description: "连接、工具和授权" },
  { id: "prompts", label: "系统提示词", description: "版本、发布和回滚" },
  { id: "runtime", label: "模型与运行策略", description: "模型、沙箱和审批" },
];

type SystemAdminPageProps = {
  section?: SystemSection;
  onSectionChange?: (section: SystemSection) => void;
};

export function SystemAdminPage({
  section,
  onSectionChange,
}: SystemAdminPageProps = {}) {
  const { update: updateSession } = useSession();
  const [access, setAccess] = useState<SystemAccess | "loading">("loading");
  const [internalSection, setInternalSection] = useState<SystemSection>("overview");
  const [message, setMessage] = useState("");
  const activeSection = section ?? internalSection;
  const navigate = onSectionChange ?? setInternalSection;

  useEffect(() => {
    let active = true;
    void getSystemAccess()
      .then((result) => {
        if (active) setAccess(result);
      })
      .catch(() => {
        if (active) setAccess("forbidden");
      });
    return () => {
      active = false;
    };
  }, []);

  async function claimAdministrator() {
    setMessage("正在初始化...");
    try {
      await bootstrapSystemAdministrator();
      await updateSession();
      setAccess("administrator");
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "初始化失败");
    }
  }

  if (access === "loading") {
    return (
      <section className="system-console-state" aria-label="正在加载系统控制台">
        <span className="system-loader" />
        <strong>正在校验管理权限</strong>
        <p>读取用户角色与系统配置。</p>
      </section>
    );
  }

  if (access === "bootstrap_required") {
    return (
      <section className="system-bootstrap">
        <div className="system-bootstrap-mark">01</div>
        <span>首次设置</span>
        <h1>初始化系统管理员</h1>
        <p>当前系统还没有管理员。此操作只能执行一次，完成后由管理员维护其他用户角色。</p>
        <button type="button" onClick={() => void claimAdministrator()}>
          设为当前账号
        </button>
        {message && <small role="status">{message}</small>}
      </section>
    );
  }

  if (access !== "administrator") {
    return (
      <section className="system-console-state denied">
        <span>权限受限</span>
        <strong>你没有系统管理权限</strong>
        <p>请联系系统管理员为当前账号分配管理员角色。</p>
      </section>
    );
  }

  return (
    <section className="system-console">
      <header className="system-console-header">
        <div>
          <span>GOVERNANCE / CONTROL</span>
          <h1>系统控制台</h1>
          <p>统一维护访问边界、运行能力和全局行为。</p>
        </div>
        <div className="system-environment">
          <i />
          <span>当前环境</span>
          <strong>运行中</strong>
        </div>
      </header>

      <div className="system-console-main">
        {activeSection === "overview" && <SystemOverview onNavigate={navigate} />}
        {activeSection === "users" && <SystemUsersPanel />}
        {activeSection === "mcp" && <SystemMcpPanel />}
        {activeSection === "prompts" && <SystemPromptsPanel />}
        {activeSection === "runtime" && <SystemRuntimePanel />}
      </div>
    </section>
  );
}

function SystemOverview({
  onNavigate,
}: {
  onNavigate: (section: SystemSection) => void;
}) {
  const cards = systemSections.filter((section) => section.id !== "overview");
  return (
    <div className="system-overview">
      <div className="system-section-heading">
        <div><span>OVERVIEW</span><h2>治理域</h2></div>
        <p>所有变更均在服务端校验，并记录操作者与目标。</p>
      </div>
      <div className="system-overview-grid">
        {cards.map((card, index) => (
          <button key={card.id} type="button" onClick={() => onNavigate(card.id)}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{card.label}</strong>
            <p>{card.description}</p>
            <em>进入管理 →</em>
          </button>
        ))}
      </div>
      <aside className="system-boundary-note">
        <strong>安全边界</strong>
        <p>敏感配置不在浏览器回显；停用、发布和运行策略只影响后续请求，正在执行的分析不会被中途改写。</p>
      </aside>
    </div>
  );
}
