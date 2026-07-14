import type { FormEvent } from "react";

interface AnalysisFormProps {
  question: string;
  disabled: boolean;
  onQuestionChange: (question: string) => void;
  onSubmit: () => void;
}

export function AnalysisForm({ question, disabled, onQuestionChange, onSubmit }: AnalysisFormProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="analysis-form" onSubmit={handleSubmit}>
      <label htmlFor="analysis-question">你的问题</label>
      <div className="question-row">
        <textarea
          id="analysis-question"
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          placeholder="例如：本月各渠道的销售额有什么变化？"
          rows={3}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled}>
          {disabled ? "分析中..." : "开始分析"}
        </button>
      </div>
    </form>
  );
}

