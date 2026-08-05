"use client";

import { useEffect, useMemo, useState } from "react";

import {
  createPromptDraft,
  listManagedPrompts,
  publishPrompt,
  rollbackPrompt,
  type ManagedPrompt,
} from "../system-api";

export function SystemPromptsPanel() {
  const [prompts, setPrompts] = useState<ManagedPrompt[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState("");
  const selected = prompts.find((prompt) => prompt.id === selectedId) || prompts[0] || null;

  async function refresh(preferredId?: string) {
    try {
      const rows = await listManagedPrompts();
      setPrompts(rows);
      setSelectedId(preferredId || rows[0]?.id || null);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提示词加载失败");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const published = useMemo(
    () => prompts.find((prompt) => prompt.status === "published") || null,
    [prompts],
  );

  function startDraft() {
    setDraft(published?.content || selected?.content || "");
    setEditing(true);
  }

  async function saveDraft() {
    if (!draft.trim()) return;
    setMessage("正在保存草稿...");
    try {
      const created = await createPromptDraft({
        promptKey: published?.promptKey || selected?.promptKey || "analysis_system",
        name: published?.name || selected?.name || "分析系统提示词",
        description: published?.description || selected?.description || null,
        content: draft,
      });
      setEditing(false);
      await refresh(created.id);
      setMessage(`草稿 v${created.version} 已保存`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "草稿保存失败");
    }
  }

  async function publish(version: ManagedPrompt) {
    setMessage("正在发布...");
    try {
      const saved = await publishPrompt(version.id);
      await refresh(saved.id);
      setMessage(`v${saved.version} 已发布，将影响后续分析`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "发布失败");
    }
  }

  async function rollback(version: ManagedPrompt) {
    setMessage("正在创建回滚版本...");
    try {
      const saved = await rollbackPrompt(version.id);
      await refresh(saved.id);
      setMessage(`已回滚并发布为 v${saved.version}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "回滚失败");
    }
  }

  return (
    <div className="system-domain-panel">
      <div className="system-section-heading">
        <div><span>BEHAVIOR</span><h2>系统提示词</h2></div>
        <p>以不可变版本控制全局分析行为；发布只影响后续请求。</p>
      </div>
      <div className="system-prompt-toolbar">
        <div>
          <span>当前发布</span>
          <strong>{published ? `v${published.version}` : "未发布"}</strong>
          <small>{published?.publishedAt ? new Date(published.publishedAt).toLocaleString("zh-CN") : "使用内置默认值"}</small>
        </div>
        <button type="button" onClick={startDraft}>新建草稿</button>
      </div>
      <div className="system-master-detail prompts">
        <div className="system-version-list">
          <header><strong>版本记录</strong><span>{prompts.length}</span></header>
          {prompts.map((prompt) => (
            <button
              type="button"
              key={prompt.id}
              className={selected?.id === prompt.id ? "active" : ""}
              onClick={() => setSelectedId(prompt.id)}
            >
              <span><strong>v{prompt.version}</strong><small>{new Date(prompt.createdAt).toLocaleDateString("zh-CN")}</small></span>
              <em className={prompt.status}>{prompt.status === "published" ? "已发布" : prompt.status === "draft" ? "草稿" : "历史"}</em>
            </button>
          ))}
        </div>
        <article className="system-prompt-editor">
          {editing ? (
            <>
              <header><div><span>DRAFT</span><h3>编辑新版本</h3></div></header>
              <textarea value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="系统提示词内容" />
              <footer>
                <button type="button" className="secondary" onClick={() => setEditing(false)}>取消</button>
                <button type="button" onClick={() => void saveDraft()}>保存草稿</button>
              </footer>
            </>
          ) : selected ? (
            <>
              <header>
                <div><span>{selected.promptKey}</span><h3>{selected.name} · v{selected.version}</h3></div>
                <em className={selected.status}>{selected.status}</em>
              </header>
              <pre>{selected.content}</pre>
              <footer>
                {selected.status === "draft" && <button type="button" onClick={() => void publish(selected)}>发布版本</button>}
                {selected.status === "archived" && <button type="button" onClick={() => void rollback(selected)}>回滚到此版本</button>}
                <button type="button" className="secondary" onClick={startDraft}>基于当前新建草稿</button>
              </footer>
            </>
          ) : <div className="system-empty">暂无提示词版本</div>}
        </article>
      </div>
      {message && <p className="system-inline-message" role="status">{message}</p>}
    </div>
  );
}
