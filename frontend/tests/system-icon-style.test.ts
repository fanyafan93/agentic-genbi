import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";

describe("system navigation icon", () => {
  test("uses the shared toolbar outline and a sliders glyph", () => {
    const workspace = readFileSync(
      resolve(process.cwd(), "src/modules/analysis/components/AnalysisWorkspace.tsx"),
      "utf8",
    );
    const styles = readFileSync(
      resolve(process.cwd(), "src/app/globals.css"),
      "utf8",
    );

    expect(workspace).toContain('<circle cx="16" cy="7" r="2" />');
    expect(workspace).toContain('<circle cx="8" cy="17" r="2" />');
    expect(styles).toContain(".icon-btn.admin-nav { margin-top: 0; }");
    expect(styles).not.toMatch(
      /\.icon-btn\.admin-nav\s*\{[^}]*border-top:/,
    );
    expect(styles).not.toMatch(
      /\.icon-btn\.admin-nav\s*\{[^}]*padding-top:/,
    );
  });
});
