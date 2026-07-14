import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Home from "../src/app/page";

describe("MVP skeleton page", () => {
  it("identifies the project as being in the scaffold stage", () => {
    const page = renderToStaticMarkup(createElement(Home));

    expect(page).toContain("项目骨架阶段");
  });
});
