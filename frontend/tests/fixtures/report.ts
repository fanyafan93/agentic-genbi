import type { Report } from "../../src/modules/analysis/types/report";

export const reportFixture: Report = {
  id: "report_sales",
  title: "渠道销售概览",
  subtitle: "2026-08",
  ownerId: "owner-1",
  turnId: "turn-1",
  sourceSessionId: "session-1",
  isExample: false,
  layout: {
    root: { props: {} },
    content: [
      {
        type: "FilterBlock",
        props: { id: "filters", filterIds: ["region"] },
      },
      {
        type: "ChartBlock",
        props: { id: "chart", chartId: "sales-chart" },
      },
      {
        type: "TableBlock",
        props: { id: "table", tableId: "sales-table" },
      },
    ],
    zones: {},
  },
  filters: {
    region: {
      type: "select",
      label: "区域",
      defaultValue: "华东",
      options: [{ label: "华东", value: "华东" }],
    },
  },
  charts: {
    "sales-chart": {
      queryId: "sales-query",
      option: { series: [{ type: "bar" }] },
    },
  },
  tables: {
    "sales-table": {
      queryId: "sales-query",
      options: {
        columns: [{ field: "region", title: "区域" }],
      },
    },
  },
  queries: {
    "sales-query": {
      dataSource: "doris",
      sql: "SELECT region, SUM(amount) amount FROM sales WHERE region = :region GROUP BY region",
      parameters: {
        region: { filterId: "region", type: "string" },
      },
      pagination: false,
    },
  },
  createdAt: "2026-08-05T00:00:00.000Z",
  updatedAt: "2026-08-05T00:00:00.000Z",
};
