/**
 * @vitest-environment jsdom
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { FlowNodeView } from "../src/modules/analysis/components/FlowNodeView";

describe("FlowNodeView", () => {
  test("renders thinking state separately from agent content", () => {
    const view = render(
      <ol>
        <FlowNodeView
          node={{
            id: "agent-1",
            role: "agent",
            content: "",
            thinking: true,
          }}
        />
      </ol>,
    );

    expect(view.container.textContent).toContain("思考中...");
  });

  test("renders agent content exactly after thinking state is cleared", () => {
    const view = render(
      <ol>
        <FlowNodeView
          node={{
            id: "agent-1",
            role: "agent",
            content: "早上好！今天有什么需要我帮忙的吗？",
            thinking: false,
          }}
        />
      </ol>,
    );

    expect(view.container.textContent).toContain("早上好！今天有什么需要我帮忙的吗？");
    expect(view.container.textContent).not.toContain("思考中");
  });

  test("renders tool activity with an icon-style label and no status copy", () => {
    const view = render(
      <ol>
        <FlowNodeView
          node={{
            id: "agent-1",
            role: "agent",
            content: "",
            activity: [
              {
                kind: "tool",
                label: "工具调用：BI_doris / mysql_query",
                state: "done",
                detail: "SELECT 1",
                count: 2,
                details: ["SELECT 1", "SELECT 2"],
              },
            ],
          }}
        />
      </ol>,
    );

    expect(screen.getByText("BI_doris / mysql_query ×2")).toBeTruthy();
    expect(view.container.textContent).not.toContain("工具调用");
    expect(view.container.textContent).not.toContain("已完成");
  });

  test("renders completed execution as collapsed nested Codex-style process before the final answer", () => {
    render(
      <ol>
        <FlowNodeView
          node={{
            id: "agent-1",
            role: "agent",
            content: "最终结论。",
            processRunning: false,
            processStartedAt: "2026-08-05T10:00:00.000Z",
            processCompletedAt: "2026-08-05T10:01:36.000Z",
            activity: [
              { kind: "reasoning", content: "正在核验数据。", itemId: "reasoning-1:0" },
              {
                kind: "tool",
                label: "BI_doris / mysql_query",
                state: "done",
                detail: "Arguments:\nSELECT 1\n\nResult:\n1 row",
                itemId: "tool-1",
              },
            ],
          }}
        />
      </ol>,
    );

    const process = screen.getByRole("group", { name: "执行过程" });
    expect(process.hasAttribute("open")).toBe(false);
    expect(screen.getByText("分析了 1分36秒")).toBeTruthy();
    expect(screen.getByText("最终结论。")).toBeTruthy();

    fireEvent.click(screen.getByText("分析了 1分36秒"));
    expect(screen.getByText("正在核验数据。")).toBeTruthy();
    expect(screen.getByRole("group", { name: "执行步骤 正在核验数据。" }).hasAttribute("open")).toBe(false);
    expect(screen.getByLabelText("工具 BI_doris / mysql_query").hasAttribute("open")).toBe(false);
  });

  test("starts execution and the current tool group expanded while running", () => {
    render(
      <ol>
        <FlowNodeView
          node={{
            id: "agent-1",
            role: "agent",
            content: "",
            processRunning: true,
            processStartedAt: "2026-08-05T10:00:00.000Z",
            activity: [
              { kind: "reasoning", content: "正在查询数据。", itemId: "reasoning-1:0" },
              {
                kind: "tool",
                label: "BI_doris / mysql_query",
                state: "running",
                detail: "Arguments:\nSELECT 1",
                itemId: "tool-1",
              },
            ],
          }}
        />
      </ol>,
    );

    expect(screen.getByRole("group", { name: "执行过程" }).hasAttribute("open")).toBe(true);
    expect(screen.getByRole("group", { name: "执行步骤 正在查询数据。" }).hasAttribute("open")).toBe(true);
    expect(screen.getByLabelText("工具 BI_doris / mysql_query").hasAttribute("open")).toBe(false);
  });
});
