/**
 * @vitest-environment jsdom
 */
import { render, screen } from "@testing-library/react";
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
});
