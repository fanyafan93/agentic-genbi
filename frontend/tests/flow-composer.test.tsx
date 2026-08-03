/**
 * @vitest-environment jsdom
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { FlowComposer } from "../src/modules/analysis/components/FlowComposer";

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
});
