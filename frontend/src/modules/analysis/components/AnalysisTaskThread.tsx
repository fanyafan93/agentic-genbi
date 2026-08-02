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
  onStartFromSuggestion: (suggestionId: string, title: string) => void;
  onSendMessage: (content: string) => void;
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
}: Props) {
  const threadScrollRef = useRef<HTMLDivElement>(null);
  const lastNodeCountRef = useRef<number>(-1);
  const streamTailRef = useRef<number>(-1);
  const lastTaskKeyRef = useRef<string | null>(taskKey);
  const statusLabel = running ? "分析中" : isNewTask ? "等待提问" : "";

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
        <div>
          <h1>{title}</h1>
          {statusLabel ? <em>{statusLabel}</em> : null}
        </div>
      </header>
      {assetNotice && <div className="asset-notice" role="status">{assetNotice}</div>}
      <div className="thread-scroll" ref={threadScrollRef}>
        {nodes.length === 0 ? (
          <Suggestions onSelect={onStartFromSuggestion} />
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
        placeholder={isNewTask ? "输入待解决的业务问题，按回车发送" : "有什么问题，或想继续分析什么？"}
        onSubmit={onSendMessage}
      />
    </div>
  );
}
