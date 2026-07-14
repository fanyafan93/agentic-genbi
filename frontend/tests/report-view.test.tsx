import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ReportView } from "../src/features/analysis/ReportView";
import { fixedTask } from "./fixtures/analysis";

describe("ReportView", () => {
  it("renders the SQL, summary, and table without inventing a chart", () => {
    const markup = renderToStaticMarkup(createElement(ReportView, { report: fixedTask.report! }));

    expect(markup).toContain("固定销售概览");
    expect(markup).toContain("SELECT &#x27;fixed&#x27; AS report_name");
    expect(markup).toContain("report_name");
    expect(markup).toContain("fixed");
    expect(markup).not.toContain("图表");
  });
});

