"use client";

import type { AnalysisMode } from "../agentClients";

type Props = {
  value: AnalysisMode;
  onChange: (mode: AnalysisMode) => void;
};

const modes: { id: AnalysisMode; label: string; description: string }[] = [
  { id: "quick", label: "快速分析", description: "少追问，先出初稿" },
  { id: "deep", label: "深度分析", description: "先确认，再沉淀" },
];

export function AnalysisModeToggle({ value, onChange }: Props) {
  return (
    <div className="analysis-mode-toggle" role="radiogroup" aria-label="分析模式">
      {modes.map((mode) => (
        <button
          key={mode.id}
          type="button"
          className={value === mode.id ? "active" : ""}
          aria-checked={value === mode.id}
          role="radio"
          onClick={() => onChange(mode.id)}
        >
          <span>{mode.label}</span>
          <small>{mode.description}</small>
        </button>
      ))}
    </div>
  );
}
