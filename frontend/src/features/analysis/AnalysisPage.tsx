"use client";

import { useEffect, useRef, useState } from "react";

import { createAnalysisTask, getAnalysisTask } from "../../services/analysis-api";
import type { AnalysisTaskStatus, TaskState } from "../../types/analysis";
import { AnalysisForm } from "./AnalysisForm";
import { ReportView } from "./ReportView";
import { TaskStatus } from "./TaskStatus";

const terminalStates: TaskState[] = ["succeeded", "failed", "requires_input"];

export function AnalysisPage({ pollIntervalMs = 800 }: { pollIntervalMs?: number }) {
  const [question, setQuestion] = useState("");
  const [task, setTask] = useState<AnalysisTaskStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollingRef = useRef(false);

  useEffect(() => {
    if (!task || terminalStates.includes(task.status) || pollingRef.current) return;
    pollingRef.current = true;
    const timer = window.setTimeout(async () => {
      try {
        const nextTask = await getAnalysisTask(task.task_id);
        setTask(nextTask);
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : "轮询分析任务失败");
        setTask(null);
      } finally {
        pollingRef.current = false;
      }
    }, pollIntervalMs);
    return () => window.clearTimeout(timer);
  }, [pollIntervalMs, task]);

  async function submitQuestion() {
    const normalizedQuestion = question.trim();
    if (!normalizedQuestion) {
      setError("请输入你的分析问题");
      return;
    }
    setError(null);
    setTask(null);
    setSubmitting(true);
    try {
      setTask(await createAnalysisTask(normalizedQuestion));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "创建分析任务失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="workspace-shell">
      <section className="hero-block">
        <div className="brand-line"><span className="brand-mark">◆</span><span>AGENTIC GENBI / MVP</span></div>
        <h1>让数据回答<br /><em>真正的问题。</em></h1>
        <p className="hero-copy">用自然语言描述你想知道的事。分析 Agent 会整理查询、过程与证据，给你一份可复核的答案。</p>
        <AnalysisForm question={question} disabled={submitting || task?.status === "queued" || task?.status === "running"} onQuestionChange={setQuestion} onSubmit={submitQuestion} />
        {error && <p className="form-error" role="alert">{error}</p>}
      </section>
      <section className="results-block">
        <TaskStatus task={task} />
        {task?.report && <ReportView report={task.report} />}
        {!task && !error && <div className="empty-state"><span>01</span><p>你的下一次分析会出现在这里。</p></div>}
      </section>
    </main>
  );
}

