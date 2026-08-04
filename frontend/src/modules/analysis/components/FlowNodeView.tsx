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

function cleanToolLabel(label: string): string {
  return label.replace(/^工具调用：\s*/, "");
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
          {activity.length > 0 && (
            <ol className="agent-activity" aria-label="本轮执行过程">
              {activity.map((item, index) => (
                <li className={`agent-activity-item activity-${item.kind}`} key={`${item.itemId ?? item.kind}-${index}`}>
                  {item.kind === "message" ? (
                    <div className="message-body-markdown activity-message-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <>
                      {item.detail ? (
                        <details className="tool-step-detail" aria-label={`工具 ${cleanToolLabel(item.label)}`}>
                          <summary>
                            <span className="agent-activity-tool-icon" aria-hidden="true">TOOL</span>
                            <strong>{cleanToolLabel(item.label)}{item.count && item.count > 1 ? ` ×${item.count}` : ""}</strong>
                          </summary>
                          <pre>{(item.details && item.details.length > 0 ? item.details : [item.detail]).join("\n\n")}</pre>
                        </details>
                      ) : (
                        <span className="agent-activity-tool-label" aria-label={`工具 ${cleanToolLabel(item.label)}`}>
                          <span className="agent-activity-tool-icon" aria-hidden="true">TOOL</span>
                          <strong>{cleanToolLabel(item.label)}{item.count && item.count > 1 ? ` ×${item.count}` : ""}</strong>
                        </span>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ol>
          )}
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
