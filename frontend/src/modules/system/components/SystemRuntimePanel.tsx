"use client";

import { useEffect, useState } from "react";

import type { SystemRuntimePolicy } from "../runtime-policy";
import {
  getRuntimePolicy,
  saveRuntimePolicy,
  type RuntimeStatus,
} from "../system-api";

export function SystemRuntimePanel() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [draft, setDraft] = useState<SystemRuntimePolicy | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void getRuntimePolicy()
      .then((value) => {
        setRuntime(value);
        setDraft(value);
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "运行策略加载失败"));
  }, []);

  async function save() {
    if (!draft) return;
    setMessage("正在应用策略...");
    try {
      const saved = await saveRuntimePolicy(draft);
      setRuntime(saved);
      setDraft(saved);
      setMessage("策略已保存，将用于后续分析");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "策略保存失败");
    }
  }

  return (
    <div className="system-domain-panel">
      <div className="system-section-heading">
        <div><span>EXECUTION</span><h2>模型与运行策略</h2></div>
        <p>控制后续分析使用的模型、工具开放程度和执行边界。</p>
      </div>
      {draft && runtime ? (
        <>
          <div className="system-runtime-banner">
            <div><i className={runtime.enabled ? "online" : ""} /><span><strong>{runtime.enabled ? "运行服务正常" : "运行服务未启用"}</strong><small>提供方：{runtime.provider}</small></span></div>
            <span>修改不会中断正在执行的分析</span>
          </div>
          <div className="system-policy-grid">
            <label>
              <span>默认模型</span>
              <small>用于后续创建和继续的分析任务</small>
              <input value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} />
            </label>
            <label>
              <span>审批策略</span>
              <small>决定工具调用是否进入自动安全审查</small>
              <select value={draft.approvalMode} onChange={(event) => setDraft({ ...draft, approvalMode: event.target.value as SystemRuntimePolicy["approvalMode"] })}>
                <option value="auto_review">自动安全审查</option>
                <option value="deny_all">拒绝全部审批请求</option>
              </select>
            </label>
            <label>
              <span>沙箱边界</span>
              <small>限制运行过程允许触碰的文件范围</small>
              <select value={draft.sandbox} onChange={(event) => setDraft({ ...draft, sandbox: event.target.value as SystemRuntimePolicy["sandbox"] })}>
                <option value="read_only">只读</option>
                <option value="workspace_write">允许写入工作区</option>
              </select>
            </label>
            <label className="system-policy-toggle">
              <span><strong>内置工具</strong><small>允许运行时使用默认工具集合</small></span>
              <button
                type="button"
                className={`system-switch ${draft.defaultToolsEnabled ? "on" : ""}`}
                aria-label="切换内置工具"
                onClick={() => setDraft({ ...draft, defaultToolsEnabled: !draft.defaultToolsEnabled })}
              ><span /></button>
            </label>
          </div>
          <aside className="system-policy-warning">
            <strong>受保护边界</strong>
            <p>全权限沙箱不会在管理后台开放。数据源只读、权限判断和审计仍由服务端强制执行。</p>
          </aside>
          <div className="system-form-actions">
            <button type="button" className="secondary" onClick={() => setDraft(runtime)}>放弃更改</button>
            <button type="button" onClick={() => void save()}>保存并应用</button>
          </div>
        </>
      ) : <div className="system-empty">正在读取运行策略...</div>}
      {message && <p className="system-inline-message" role="status">{message}</p>}
    </div>
  );
}
