"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";

type Props = {
  disabled?: boolean;
  running?: boolean;
  placeholder?: string;
  onSubmit: (value: string) => void;
  onStop?: () => void;
};

export function FlowComposer({ disabled, running = false, placeholder, onSubmit, onStop }: Props) {
  const [value, setValue] = useState("");

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
