"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { FlowActivity, FlowNode as FlowNodeData } from "../hooks/use-flow";

const UserAvatar = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="8" r="3.4" />
    <path d="M4.5 19.5c0-3.6 3.4-5.7 7.5-5.7s7.5 2.1 7.5 5.7" />
  </svg>
);

const AgentAvatar = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
    <rect x="4" y="7" width="16" height="12" rx="3.5" />
    <circle cx="9" cy="13" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="15" cy="13" r="1.2" fill="currentColor" stroke="none" />
    <path d="M9 4.5v2.5" />
    <path d="M15 4.5v2.5" />
    <path d="M2.5 12v2.5" />
    <path d="M21.5 12v2.5" />
  </svg>
);

const AskAvatar = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9.5 8a2.5 2.5 0 0 1 5 0c0 1.5-1.4 2.1-2.4 2.8-.7.5-1.1 1-1.1 2.2" />
    <circle cx="12" cy="16.5" r=".8" fill="currentColor" stroke="none" />
  </svg>
);

function cleanToolLabel(label: string): string {
  return label.replace(/^工具调用：\s*/, "");
}

type AgentNode = Extract<FlowNodeData, { role: "agent" }>;
type ToolActivity = Extract<FlowActivity, { kind: "tool" }>;
type ProcessEntry = Extract<FlowActivity, { kind: "reasoning" | "message" }>;
type ProcessBlock =
  | { kind: "note"; entry: ProcessEntry }
  | { kind: "group"; entry: ProcessEntry; tools: ToolActivity[] }
  | { kind: "tools"; tools: ToolActivity[] };

function formatDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.round(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}秒`;
  if (seconds === 0) return `${minutes}分`;
  return `${minutes}分${seconds}秒`;
}

function processSummary(node: AgentNode): string {
  if (node.processRunning) return "正在处理";
  const started = node.processStartedAt ? Date.parse(node.processStartedAt) : Number.NaN;
  const completed = node.processCompletedAt ? Date.parse(node.processCompletedAt) : Number.NaN;
  if (Number.isFinite(started) && Number.isFinite(completed) && completed >= started) {
    return `分析了 ${formatDuration(completed - started)}`;
  }
  return "执行过程";
}

function groupProcessActivity(activity: FlowActivity[]): ProcessBlock[] {
  const blocks: ProcessBlock[] = [];
  for (const entry of activity) {
    if (entry.kind === "tool") {
      const previous = blocks.at(-1);
      if (previous?.kind === "note") {
        blocks[blocks.length - 1] = { kind: "group", entry: previous.entry, tools: [entry] };
      } else if (previous?.kind === "group" || previous?.kind === "tools") {
        previous.tools.push(entry);
      } else {
        blocks.push({ kind: "tools", tools: [entry] });
      }
      continue;
    }
    blocks.push({ kind: "note", entry });
  }
  return blocks;
}

function renderToolActivity(tool: ToolActivity) {
  const label = `${cleanToolLabel(tool.label)}${tool.count && tool.count > 1 ? ` ×${tool.count}` : ""}`;
  return (
    <div
      className={`agent-activity-item activity-tool ${tool.state}`}
      key={tool.itemId ?? tool.label}
    >
      {tool.detail ? (
        <details className="tool-step-detail" aria-label={`工具 ${cleanToolLabel(tool.label)}`}>
          <summary>
            <span className="agent-activity-tool-icon" aria-hidden="true">TOOL</span>
            <strong>{label}</strong>
          </summary>
          <pre>{(tool.details && tool.details.length > 0 ? tool.details : [tool.detail]).join("\n\n")}</pre>
        </details>
      ) : (
        <span className="agent-activity-tool-label" aria-label={`工具 ${cleanToolLabel(tool.label)}`}>
          <span className="agent-activity-tool-icon" aria-hidden="true">TOOL</span>
          <strong>{label}</strong>
        </span>
      )}
    </div>
  );
}

function AgentStepGroup({ entry, tools }: { entry: ProcessEntry; tools: ToolActivity[] }) {
  const running = tools.some((tool) => tool.state === "running");
  const [stepOpen, setStepOpen] = useState(running);
  const wasRunning = useRef(running);

  useEffect(() => {
    if (running && !wasRunning.current) setStepOpen(true);
    if (!running && wasRunning.current) setStepOpen(false);
    wasRunning.current = running;
  }, [running]);

  return (
    <details
      className="agent-step-group"
      aria-label={`执行步骤 ${entry.content}`}
      open={stepOpen}
      onToggle={(event) => setStepOpen(event.currentTarget.open)}
    >
      <summary>{entry.content}</summary>
      <div className="agent-step-tools">{tools.map(renderToolActivity)}</div>
    </details>
  );
}

function AgentProcess({ node }: { node: AgentNode }) {
  const activity = node.activity ?? [];
  const [processOpen, setProcessOpen] = useState(Boolean(node.processRunning));
  const wasRunning = useRef(Boolean(node.processRunning));

  useEffect(() => {
    if (node.processRunning && !wasRunning.current) setProcessOpen(true);
    if (!node.processRunning && wasRunning.current) setProcessOpen(false);
    wasRunning.current = Boolean(node.processRunning);
  }, [node.processRunning]);

  if (activity.length === 0) return null;

  return (
    <details
      className="agent-process"
      aria-label="执行过程"
      open={processOpen}
      onToggle={(event) => setProcessOpen(event.currentTarget.open)}
    >
      <summary>{processSummary(node)}</summary>
      <ol className="agent-activity" aria-label="本轮执行过程">
        {groupProcessActivity(activity).map((block, index) => (
          <li className={`agent-process-block block-${block.kind}`} key={`${block.kind}-${index}`}>
            {block.kind === "note" ? (
              <div className="message-body-markdown activity-message-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.entry.content}</ReactMarkdown>
              </div>
            ) : block.kind === "group" ? (
              <AgentStepGroup entry={block.entry} tools={block.tools} />
            ) : (
              <div className="agent-step-tools">{block.tools.map(renderToolActivity)}</div>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
}

type Props = {
  node: FlowNodeData;
  onReply?: (optionId: string) => void;
};

export function FlowNodeView({ node, onReply }: Props) {
  if (node.role === "user") {
    return (
      <li className="flow-node flow-user">
        <div className="flow-marker" aria-hidden="true">
          <div className="avatar avatar-user">
            <UserAvatar />
          </div>
        </div>
        <div className="flow-card">
          <p>{node.content}</p>
        </div>
      </li>
    );
  }

  if (node.role === "agent") {
    const activity = node.activity ?? [];
    const steps = activity.length > 0 ? [] : node.steps ?? [];
    return (
      <li className="flow-node flow-agent">
        <div className="flow-marker" aria-hidden="true">
          <div className="avatar avatar-agent">
            <AgentAvatar />
          </div>
        </div>
        <div className="flow-card">
          <AgentProcess node={node} />
          {node.thinking && (
            <div className="message-body-markdown flow-content flow-thinking">思考中...</div>
          )}
          {(node.content || (!node.thinking && activity.length === 0)) && (
            <div className="message-body-markdown flow-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{node.content || "\u00A0"}</ReactMarkdown>
            </div>
          )}
          {steps.length > 0 && (
            <ol className="timeline" role="list">
              {steps.map((step, index) => (
                <li className={`timeline-step ${step.state}`} key={`${step.itemId ?? step.label}-${index}`}>
                  <span className="timeline-dot" aria-hidden="true" />
                  {step.detail ? (
                    <details className="tool-step-detail">
                      <summary><strong>{step.label}</strong></summary>
                      <pre>{step.detail}</pre>
                    </details>
                  ) : (
                    <strong>{step.label}</strong>
                  )}
                  {step.state !== "done" && (
                    <em>{step.state === "running" ? "进行中" : "等待中"}</em>
                  )}
                </li>
              ))}
            </ol>
          )}
          {node.debug && node.debug.length > 0 && (
            <div className="debug-events">
              {node.debug.map((item, index) => (
                <details key={`${item.title}-${index}`} className="debug-event">
                  <summary>{item.title}</summary>
                  <pre>{item.content}</pre>
                </details>
              ))}
            </div>
          )}
        </div>
      </li>
    );
  }

  return (
    <li className={`flow-node flow-ask ${node.current ? "is-current" : ""}`}>
      <div className="flow-marker" aria-hidden="true">
        <div className="avatar avatar-ask">
          <AskAvatar />
        </div>
      </div>
      <div className="flow-card flow-card-ask">
        <p>{node.question}</p>
        <div className="chips">
          {node.options.map((opt) => (
            <button key={opt.id} type="button" disabled={!node.current} onClick={() => onReply?.(opt.id)}>
              {opt.label}
            </button>
          ))}
        </div>
      </div>
    </li>
  );
}
