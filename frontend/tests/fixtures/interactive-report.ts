import type { InteractiveReport } from "../../src/modules/analysis/types/interactive-report";

export const interactiveReportFixture: InteractiveReport = {
  artifactType: "interactive_report",
  schemaVersion: "1.0",
  id: "report_test_channel_sales",
  title: "渠道销售分析",
  subtitle: "测试报告",
  renderer: "puck",
  source: {
    threadId: "thread_test_channel_sales",
    turnId: "turn_test_channel_sales",
  },
  document: {
    root: { props: { title: "渠道销售分析" } },
    content: [],
    zones: {},
  },
  filters: [],
  queries: {},
  chartSpecs: {},
  gridSpecs: {},
};
