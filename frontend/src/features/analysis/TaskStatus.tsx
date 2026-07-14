import type { AnalysisTaskStatus as TaskStatusData } from "../../types/analysis";

const statusLabels = {
  queued: "排队中",
  running: "分析中",
  succeeded: "已完成",
  failed: "失败",
  requires_input: "需要补充信息",
} as const;

const stepStateLabels = {
  started: "进行中",
  succeeded: "已完成",
  failed: "失败",
} as const;

export function TaskStatus({ task }: { task: TaskStatusData | null }) {
  if (!task) return null;

  return (
    <section className={`task-status task-status-${task.status}`} aria-live="polite">
      <span className="status-kicker">ANALYSIS TASK</span>
      <strong>{statusLabels[task.status]}</strong>
      <span className="task-id">#{task.task_id.slice(0, 8)}</span>
      {task.steps.length > 0 && (
        <ol className="step-list">
          {task.steps.map((step) => (
            <li key={step.step_id} data-state={step.status}>
              <div className="step-heading">
                <span className="step-sequence">{String(step.sequence).padStart(2, "0")}</span>
                <strong>{step.title}</strong>
                <span className="step-state">{stepStateLabels[step.status]}</span>
              </div>
              <div className="step-meta">
                {step.attempt !== null && <span>第 {step.attempt} 次 SQL 尝试</span>}
                {step.detail && <span>{step.detail}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
      {task.error && <p className="error-copy">{task.error.message}</p>}
    </section>
  );
}

