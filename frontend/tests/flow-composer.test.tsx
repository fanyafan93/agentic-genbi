/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { FlowComposer } from "../src/modules/analysis/components/FlowComposer";

afterEach(cleanup);

describe("FlowComposer", () => {
  test("submits on Enter and keeps Shift+Enter for new lines", () => {
    const onSubmit = vi.fn();
    render(<FlowComposer onSubmit={onSubmit} />);
    const textarea = screen.getByRole("textbox");

    fireEvent.change(textarea, { target: { value: "first line" } });
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: "first line\nsecond line" } });
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });

    expect(onSubmit).toHaveBeenCalledWith("first line\nsecond line");
    expect((textarea as HTMLTextAreaElement).value).toBe("");
  });

  test("defaults to collaboration mode and lets the user choose another UI mode", () => {
    render(<FlowComposer onSubmit={vi.fn()} />);

    const modeButton = screen.getByRole("button", { name: "分析模式：协作模式" });
    expect(modeButton.textContent).toContain("协作模式");
    expect(screen.queryByRole("listbox", { name: "选择分析模式" })).toBeNull();

    fireEvent.click(modeButton);

    expect(screen.getByRole("option", { name: /方案模式/ }).textContent).toContain(
      "只检索资料、生成步骤和 SQL 草案，不查询真实数据。",
    );
    expect(screen.getByRole("option", { name: /协作模式/ }).textContent).toContain(
      "自动执行安全操作，遇到口径冲突或高风险操作时确认。",
    );
    expect(screen.getByRole("option", { name: /托管模式/ }).textContent).toContain(
      "自动检索、查询、校验并生成报告草稿；发布、分享仍需确认。",
    );

    fireEvent.click(screen.getByRole("option", { name: /方案模式/ }));

    expect(screen.getByRole("button", { name: "分析模式：方案模式" }).textContent).toContain("方案模式");
    expect(screen.queryByRole("listbox", { name: "选择分析模式" })).toBeNull();
  });

  test("disables mode switching while a turn is running", () => {
    render(<FlowComposer running onSubmit={vi.fn()} onStop={vi.fn()} />);

    expect((screen.getByRole("button", { name: "分析模式：协作模式" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
