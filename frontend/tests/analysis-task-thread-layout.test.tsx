/**
 * @vitest-environment jsdom
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { AnalysisTaskThread } from "../src/modules/analysis/components/AnalysisTaskThread";

afterEach(cleanup);

describe("analysis task thread header", () => {
  test("places the task status at the right edge of the header", () => {
    const view = render(
      <AnalysisTaskThread
        title="新分析"
        isNewTask
        running={false}
        nodes={[]}
        assetNotice=""
        mobileHidden={false}
        taskKey={null}
        onReply={vi.fn()}
        onStartFromSuggestion={vi.fn()}
        onSendMessage={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    const header = view.container.querySelector(".thread-header");
    const status = screen.getAllByText("等待提问")[0];
    expect(header).not.toBeNull();
    expect(status.classList.contains("thread-status")).toBe(true);
    expect(status.parentElement).toBe(header);
    expect(header?.querySelector(".thread-heading")).not.toBeNull();
  });
});
