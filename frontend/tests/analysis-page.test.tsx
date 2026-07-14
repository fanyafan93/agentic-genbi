import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalysisPage } from "../src/features/analysis/AnalysisPage";
import { failedTask, fixedTask, queuedTask } from "./fixtures/analysis";

const api = vi.hoisted(() => ({
  createAnalysisTask: vi.fn(),
  getAnalysisTask: vi.fn(),
}));

vi.mock("../src/services/analysis-api", () => api);

describe("AnalysisPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("does not submit a blank question", () => {
    render(<AnalysisPage />);

    fireEvent.click(screen.getByRole("button", { name: "开始分析" }));

    expect(api.createAnalysisTask).not.toHaveBeenCalled();
    expect(screen.getByText("请输入你的分析问题")).toBeTruthy();
  });

  it("submits a question, polls, and renders the terminal report", async () => {
    api.createAnalysisTask.mockResolvedValue(queuedTask);
    api.getAnalysisTask.mockResolvedValue(fixedTask);
    render(<AnalysisPage pollIntervalMs={0} />);

    fireEvent.change(screen.getByLabelText("你的问题"), {
      target: { value: "查看销售概览" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始分析" }));

    await waitFor(() => expect(api.createAnalysisTask).toHaveBeenCalledWith("查看销售概览"));
    await waitFor(() => expect(screen.getByText("固定销售概览")).toBeTruthy());
    expect(api.getAnalysisTask).toHaveBeenCalledWith("task-1");
    expect(screen.getByText("SELECT 'fixed' AS report_name")).toBeTruthy();
  });

  it("stops polling when the task reaches failed", async () => {
    api.createAnalysisTask.mockResolvedValue(queuedTask);
    api.getAnalysisTask.mockResolvedValue(failedTask);
    render(<AnalysisPage pollIntervalMs={0} />);

    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "查询销售额" } });
    fireEvent.click(screen.getByRole("button", { name: "开始分析" }));

    await waitFor(() => expect(screen.getByText("查询失败，请调整问题后重试。")).toBeTruthy());
    expect(api.getAnalysisTask).toHaveBeenCalledTimes(1);
  });

  it("does not retry a task that disappeared from the backend", async () => {
    api.createAnalysisTask.mockResolvedValue(queuedTask);
    api.getAnalysisTask.mockRejectedValue(new Error("分析任务不存在或状态已因服务重启而丢失。"));
    render(<AnalysisPage pollIntervalMs={0} />);

    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "查询销售额" } });
    fireEvent.click(screen.getByRole("button", { name: "开始分析" }));

    await waitFor(() => expect(screen.getByText("分析任务不存在或状态已因服务重启而丢失。")).toBeTruthy());
    expect(api.createAnalysisTask).toHaveBeenCalledTimes(1);
    expect(api.getAnalysisTask).toHaveBeenCalledTimes(1);
  });
});
