"use client";

import { useEffect, useRef } from "react";
import type { FlowNode } from "../hooks/use-flow";
import { FlowComposer } from "./FlowComposer";
import { FlowNodeView } from "./FlowNodeView";
import { Suggestions } from "./Suggestions";

type Props = {
  title: string;
  isNewTask: boolean;
  running: boolean;
  nodes: FlowNode[];
  assetNotice: string;
  mobileHidden: boolean;
  taskKey: string | null;
  onReply: (optionId: string) => void;
  onStartFromSuggestion: (suggestionId: string, title: string) => void | Promise<void>;
  onSendMessage: (content: string) => void | Promise<void>;
  onStop: () => void;
};

export function AnalysisTaskThread({
  title,
  isNewTask,
  running,
  nodes,
  assetNotice,
  mobileHidden,
  taskKey,
  onReply,
  onStartFromSuggestion,
  onSendMessage,
  onStop,
}: Props) {
  const threadScrollRef = useRef<HTMLDivElement>(null);
  const lastNodeCountRef = useRef<number>(-1);
  const streamTailRef = useRef<number>(-1);
  const lastTaskKeyRef = useRef<string | null>(taskKey);
  const statusLabel = running ? "分析中" : isNewTask ? "等待提问" : "";
  const threadBadge = formatTaskId(taskKey);

  useEffect(() => {
    const el = threadScrollRef.current;
    if (!el) return;
    const lastAgent = [...nodes].reverse().find((node) => node.role === "agent");
    const tail = lastAgent && lastAgent.role === "agent" ? lastAgent.content.length : -1;
    const nodesChanged = nodes.length !== lastNodeCountRef.current;
    const streamChanged = tail !== streamTailRef.current;
    const taskChanged = taskKey !== lastTaskKeyRef.current;
    if (nodesChanged || streamChanged || taskChanged || lastNodeCountRef.current === -1) {
      el.scrollTop = el.scrollHeight;
      lastNodeCountRef.current = nodes.length;
      streamTailRef.current = tail;
      lastTaskKeyRef.current = taskKey;
    }
  });

  useEffect(() => {
    const id = requestAnimationFrame(() => {
      const el = threadScrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(id);
  }, [nodes.length, taskKey]);

  return (
    <div className={`thread ${mobileHidden ? "mobile-hidden" : ""}`}>
      <header className="thread-header">
        <div className="thread-heading">
          {threadBadge && <span className="thread-id-badge">{threadBadge}</span>}
          <h1>{title}</h1>
        </div>
        {statusLabel ? <em className="thread-status" role="status">{statusLabel}</em> : null}
      </header>
      {assetNotice && <div className="asset-notice" role="status">{assetNotice}</div>}
      <div className="thread-scroll" ref={threadScrollRef}>
        {nodes.length === 0 && running ? (
          <div className="flow-empty-running" role="status">
            <span />
            <strong>正在开始分析</strong>
            <small>等待模型返回第一段内容...</small>
          </div>
        ) : nodes.length === 0 && isNewTask ? (
          <Suggestions onSelect={onStartFromSuggestion} />
        ) : nodes.length === 0 ? (
          <div className="flow-empty-running" role="status">
            <span />
            <strong>等待提问</strong>
            <small>输入问题后会在这个任务里继续分析。</small>
          </div>
        ) : (
          <ol className="flow">
            {nodes.map((node) => (
              <FlowNodeView key={node.id} node={node} onReply={onReply} />
            ))}
          </ol>
        )}
      </div>
      <FlowComposer
        disabled={running}
        running={running}
        placeholder={isNewTask ? "输入待解决的业务问题，按回车发送" : "有什么问题，或想继续分析什么？"}
        onSubmit={onSendMessage}
        onStop={onStop}
      />
    </div>
  );
}

function formatTaskId(taskKey: string | null): string {
  if (!taskKey) return "";
  const parts = taskKey.split("_");
  const suffix = parts.at(-1) || taskKey;
  return suffix.slice(0, 8);
}
