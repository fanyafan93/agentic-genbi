import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TaskStatus } from "../src/features/analysis/TaskStatus";
import { fixedTask } from "./fixtures/analysis";

describe("TaskStatus", () => {
  it("renders ordered, safe execution progress with SQL attempt numbers", () => {
    const markup = renderToStaticMarkup(
      createElement(TaskStatus, {
        task: {
          ...fixedTask,
          steps: [
            {
              step_id: "step-1",
              sequence: 1,
              kind: "list_tables",
              status: "succeeded",
              title: "Reading approved tables",
              detail: "Metadata is ready.",
              attempt: null,
              started_at: "2026-07-14T06:00:00Z",
              finished_at: "2026-07-14T06:00:01Z",
            },
            {
              step_id: "step-2",
              sequence: 2,
              kind: "execute_sql",
              status: "succeeded",
              title: "Executing read-only query",
              detail: "Query completed within the server limit.",
              attempt: 2,
              started_at: "2026-07-14T06:00:01Z",
              finished_at: "2026-07-14T06:00:02Z",
            },
          ],
        },
      })
    );

    expect(markup).toContain("Reading approved tables");
    expect(markup).toContain("Metadata is ready.");
    expect(markup).toContain("第 2 次 SQL 尝试");
    expect(markup).toContain("已完成");
  });
});
