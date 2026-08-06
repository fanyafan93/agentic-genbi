"use client";

import { useState, type FocusEvent, type FormEvent, type KeyboardEvent } from "react";

const ANALYSIS_MODES = [
  {
    id: "plan",
    label: "方案模式",
    description: "只检索资料、生成步骤和 SQL 草案，不查询真实数据。",
  },
  {
    id: "collaboration",
    label: "协作模式",
    description: "自动执行安全操作，遇到口径冲突或高风险操作时确认。",
  },
  {
    id: "managed",
    label: "托管模式",
    description: "自动检索、查询、校验并生成报告草稿；发布、分享仍需确认。",
  },
] as const;

type AnalysisMode = (typeof ANALYSIS_MODES)[number];

type Props = {
  disabled?: boolean;
  running?: boolean;
  placeholder?: string;
  onSubmit: (value: string) => void;
  onStop?: () => void;
};

export function FlowComposer({ disabled, running = false, placeholder, onSubmit, onStop }: Props) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<AnalysisMode>(ANALYSIS_MODES[1]);
  const [modeMenuOpen, setModeMenuOpen] = useState(false);

  function submitCurrentValue() {
    const text = value.trim();
    if (!text) return;
    onSubmit(text);
    setValue("");
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running) {
      onStop?.();
      return;
    }
    submitCurrentValue();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    if (running) return;
    submitCurrentValue();
  }

  function handleModeBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setModeMenuOpen(false);
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? "有什么问题，或想继续分析什么？"}
        rows={3}
        disabled={disabled && !running}
      />
      <div className="composer-mode" onBlur={handleModeBlur}>
        <button
          type="button"
          className="composer-mode-trigger"
          aria-label={`分析模式：${mode.label}`}
          aria-haspopup="listbox"
          aria-expanded={modeMenuOpen}
          disabled={running}
          onClick={() => setModeMenuOpen((open) => !open)}
        >
          <span className={`composer-mode-mark is-${mode.id}`} aria-hidden="true" />
          <span>{mode.label}</span>
          <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="m5 6 3 3 3-3" />
          </svg>
        </button>
        {modeMenuOpen ? (
          <div className="composer-mode-menu" role="listbox" aria-label="选择分析模式">
            {ANALYSIS_MODES.map((item) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={item.id === mode.id}
                className={item.id === mode.id ? "is-selected" : ""}
                onClick={() => {
                  setMode(item);
                  setModeMenuOpen(false);
                }}
              >
                <span className={`composer-mode-mark is-${item.id}`} aria-hidden="true" />
                <span>
                  <strong>{item.label}{item.id === "collaboration" ? <em>默认</em> : null}</strong>
                  <small>{item.description}</small>
                </span>
                {item.id === mode.id ? (
                  <svg className="composer-mode-check" aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m3.5 8 3 3 6-6" />
                  </svg>
                ) : null}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <button
        type="submit"
        aria-label={running ? "停止回答" : "发送"}
        title={running ? "停止回答" : "发送"}
        className={`send-btn ${running ? "is-stopping" : ""}`}
        disabled={!running && (disabled || value.trim().length === 0)}
      >
        {running ? (
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
            <rect x="7" y="7" width="10" height="10" rx="1.5" />
          </svg>
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 19V6" />
            <path d="m6 11 6-6 6 6" />
          </svg>
        )}
      </button>
    </form>
  );
}
