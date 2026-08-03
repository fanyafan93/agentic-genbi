/**
 * @vitest-environment jsdom
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { FlowNodeView } from "../src/modules/analysis/components/FlowNodeView";

describe("FlowNodeView", () => {
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
