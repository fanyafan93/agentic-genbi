import { describe, expect, it } from "vitest";
import { toEChartsOption } from "../src/shared/charts/chart-adapter";
import type { ChartSpec } from "../src/modules/analysis/types/analysis";

describe("toEChartsOption", () => {
  it("converts ChartSpec and rows into an ECharts option", () => {
    const spec: ChartSpec = {
      type: "bar",
      title: "渠道销售额",
      categoryField: "channel",
      series: [{ field: "sales_amount", name: "销售额", format: "currency" }],
    };

    const option = toEChartsOption(spec, [
      { channel: "线上直营", sales_amount: 100 },
      { channel: "线下加盟", sales_amount: 80 },
    ]);

    expect(option.title).toMatchObject({ text: "渠道销售额" });
    expect(option.xAxis).toMatchObject({ type: "category", data: ["线上直营", "线下加盟"] });
    expect(option.series).toMatchObject([{ name: "销售额", type: "bar", data: [100, 80] }]);
  });
});
