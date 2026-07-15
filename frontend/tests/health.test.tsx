import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Home from "../src/app/page";

describe("MVP analysis page", () => {
  it("identifies the product as an analysis workspace", () => {
    const page = renderToStaticMarkup(createElement(Home));

    expect(page).toContain("AGENTIC GENBI");
    expect(page).toContain("开始分析");
  });
});
