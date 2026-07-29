"use client";

import { useState, type FormEvent } from "react";

type Props = {
  disabled?: boolean;
  placeholder?: string;
  onSubmit: (value: string) => void;
};

export function FlowComposer({ disabled, placeholder, onSubmit }: Props) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = value.trim();
    if (!text) return;
    onSubmit(text);
    setValue("");
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder ?? "有什么问题，或想继续探索什么？"}
        rows={3}
        disabled={disabled}
      />
      <button
        type="submit"
        aria-label="发送"
        className="send-btn"
        disabled={disabled || value.trim().length === 0}
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 19V6" />
          <path d="m6 11 6-6 6 6" />
        </svg>
      </button>
    </form>
  );
}
