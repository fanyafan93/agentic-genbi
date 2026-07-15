import type { AnalysisTaskStatus } from "../types/analysis";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function parseResponse<T>(response: Response): Promise<T> {
  const body: unknown = await response.json();
  if (!response.ok) {
    const errorValue = typeof body === "object" && body !== null && "error" in body ? body.error : null;
    const message = typeof errorValue === "object" && errorValue !== null && "message" in errorValue && typeof errorValue.message === "string"
      ? errorValue.message
      : "请求分析服务失败";
    throw new Error(message);
  }
  return body as T;
}

export async function createAnalysisTask(question: string): Promise<AnalysisTaskStatus> {
  const response = await fetch(`${apiBaseUrl}/api/v1/analysis-tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return parseResponse<AnalysisTaskStatus>(response);
}

export async function getAnalysisTask(taskId: string): Promise<AnalysisTaskStatus> {
  const response = await fetch(`${apiBaseUrl}/api/v1/analysis-tasks/${taskId}`);
  return parseResponse<AnalysisTaskStatus>(response);
}
