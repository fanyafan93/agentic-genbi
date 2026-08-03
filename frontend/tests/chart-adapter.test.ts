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

  it("infers chart fields and parses numeric strings when report rows use business labels", () => {
    const spec: ChartSpec = {
      type: "bar",
      title: "渠道销售额",
      categoryField: "channel",
      series: [{ field: "salesAmount", name: "销售额", format: "currency" }],
    };

    const option = toEChartsOption(spec, [
      { 指标: "总销售额", 数值: "¥156,609,694.80" },
      { 渠道名称: "屈臣氏", 销售额: "69,273,223.40", 销售额占比: "44.24%" },
      { 渠道名称: "松鼠单体加盟", 销售额: "11,966,273.90", 销售额占比: "7.64%" },
    ]);

    expect(option.xAxis).toMatchObject({ type: "category", data: ["屈臣氏", "松鼠单体加盟"] });
    expect(option.series).toMatchObject([{ name: "销售额", type: "bar", data: [69273223.4, 11966273.9] }]);
  });
});
