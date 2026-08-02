"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { FlowNode as FlowNodeData } from "../hooks/use-flow";

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
    const steps = node.steps ?? [];
    return (
      <li className="flow-node flow-agent">
        <div className="flow-marker" aria-hidden="true">
          <div className="avatar avatar-agent">
            <AgentAvatar />
          </div>
        </div>
        <div className="flow-card">
          <div className="message-body-markdown flow-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{node.content || "\u00A0"}</ReactMarkdown>
          </div>
          {steps.length > 0 && (
            <ol className="timeline" role="list">
              {steps.map((step, index) => (
                <li className={`timeline-step ${step.state}`} key={`${step.label}-${index}`}>
                  <span className="timeline-dot" aria-hidden="true" />
                  <strong>{step.label}</strong>
                  <em>
                    {step.state === "done"
                      ? "已完成"
                      : step.state === "running"
                      ? "进行中"
                      : "等待中"}
                  </em>
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
