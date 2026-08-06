"use client";

import { Render, type Config } from "@puckeditor/core";
import { DatePicker, Select } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import ReactECharts from "echarts-for-react";
import type { Report, ReportFilterValue } from "../types/report";
import "./report.css";
import {
  ReportProvider,
  useReportContext,
} from "./ReportContext";
import { ReportTable } from "./ReportTable";

type ReportPanelProps = {
  taskTitle: string;
  running: boolean;
  loading?: boolean;
  initialReport?: Report;
};

export function buildEChartsOption(
  option: Record<string, unknown>,
  rows: Array<Record<string, unknown>>,
): Record<string, unknown> {
  return {
    ...option,
    dataset: {
      ...asObject(option.dataset),
      source: rows,
    },
  };
}

function ChartBlock({ chartId }: { chartId: string }) {
  const { report, queryStates, executeQuery } = useReportContext();
  const chart = report.charts[chartId];
  if (!chart) {
    return (
      <div className="report-query-error" role="alert">
        未找到图表配置：{chartId}
      </div>
    );
  }
  const state = queryStates[chart.queryId];
  if (!state || state.loading) {
    return <div className="report-query-loading">图表加载中…</div>;
  }
  if (state.error) {
    return (
      <div className="report-query-error" role="alert">
        <span>{state.error}</span>
        <button
          type="button"
          onClick={() => void executeQuery(chart.queryId)}
        >
          重试
        </button>
      </div>
    );
  }
  return (
    <ReactECharts
      option={buildEChartsOption(chart.option, state.rows)}
      notMerge
      lazyUpdate
      style={{ minHeight: 320 }}
    />
  );
}

function TableBlock({ tableId }: { tableId: string }) {
  return <ReportTable tableId={tableId} />;
}

function FilterBlock({
  filterIds,
  columnSpan,
}: {
  filterIds: string[];
  columnSpan?: unknown;
}) {
  const {
    report,
    filterValues,
    setFilterValue,
  } = useReportContext();
  return (
    <div
      className="report-filter-row"
      aria-label="报告筛选条件"
      style={{
        display: "flex",
        gridColumn: reportGridColumn(columnSpan),
        minWidth: 0,
      }}
    >
      {filterIds.map((filterId) => {
        const definition = report.filters[filterId];
        if (!definition) return null;
        return (
          <label key={filterId}>
            <span>{definition.label}</span>
            <ReportFilter
              filterId={filterId}
              value={filterValues[filterId] ?? null}
              onChange={setFilterValue}
            />
          </label>
        );
      })}
    </div>
  );
}

function ReportFilter({
  filterId,
  value,
  onChange,
}: {
  filterId: string;
  value: ReportFilterValue;
  onChange: (filterId: string, value: ReportFilterValue) => void;
}) {
  const { report } = useReportContext();
  const definition = report.filters[filterId];
  if (definition.type === "select") {
    return (
      <Select
        aria-label={definition.label}
        value={typeof value === "string" ? value : undefined}
        options={definition.options}
        onChange={(next) => onChange(filterId, next)}
      />
    );
  }
  if (definition.type === "multiSelect") {
    return (
      <Select
        aria-label={definition.label}
        mode="multiple"
        value={Array.isArray(value) ? value : []}
        options={definition.options}
        onChange={(next) => onChange(filterId, next)}
      />
    );
  }
  if (definition.type === "date") {
    return (
      <DatePicker
        aria-label={definition.label}
        value={typeof value === "string" && value
          ? dayjs(value)
          : null}
        onChange={(next) => onChange(
          filterId,
          next ? next.format("YYYY-MM-DD") : null,
        )}
      />
    );
  }
  const rangeValue: [Dayjs, Dayjs] | null = (
    Array.isArray(value) && value.length === 2
  )
    ? [dayjs(value[0]), dayjs(value[1])]
    : null;
  return (
    <DatePicker.RangePicker
      aria-label={definition.label}
      style={{ width: 280, maxWidth: "100%" }}
      value={rangeValue}
      onChange={(next) => onChange(
        filterId,
        next
          ? next.map((item) => item?.format("YYYY-MM-DD") ?? "")
          : null,
      )}
    />
  );
}

export const reportPuckConfig: Config = {
  components: {
    FilterBlock: {
      fields: {
        filterIds: { type: "text" },
        columnSpan: { type: "number" },
      },
      defaultProps: { filterIds: [], columnSpan: 12 },
      render: (props) => (
        <FilterBlock
          filterIds={Array.isArray(props.filterIds)
            ? props.filterIds.map(String)
            : []}
          columnSpan={props.columnSpan}
        />
      ),
    },
    ChartBlock: {
      fields: {
        chartId: { type: "text" },
        columnSpan: { type: "number" },
      },
      defaultProps: { chartId: "", columnSpan: 12 },
      render: (props) => (
        <article
          className="report-chart-block"
          data-testid="report-chart"
          style={{
            gridColumn: reportGridColumn(props.columnSpan),
            minWidth: 0,
          }}
        >
          <ChartBlock chartId={String(props.chartId)} />
        </article>
      ),
    },
    TableBlock: {
      fields: {
        tableId: { type: "text" },
        columnSpan: { type: "number" },
      },
      defaultProps: { tableId: "", columnSpan: 12 },
      render: (props) => (
        <article
          className="report-table-block"
          data-testid="report-table"
          style={{
            gridColumn: reportGridColumn(props.columnSpan),
            minWidth: 0,
          }}
        >
          <TableBlock tableId={String(props.tableId)} />
        </article>
      ),
    },
    SectionBlock: {
      fields: { title: { type: "text" } },
      defaultProps: { title: "" },
      render: (props) => (
        <section className="report-section-title">
          <h3>{String(props.title)}</h3>
        </section>
      ),
    },
    MarkdownBlock: {
      fields: { content: { type: "textarea" } },
      defaultProps: { content: "" },
      render: (props) => (
        <div className="report-markdown">
          {String(props.content)}
        </div>
      ),
    },
  },
};

export function ReportPanel({
  taskTitle,
  loading = false,
  initialReport,
}: ReportPanelProps) {
  if (!initialReport) {
    return (
      <section
        className="report-panel report-awaiting"
        aria-label="分析结果"
      >
        <div
          className={`report-awaiting-body ${loading ? "is-busy" : "is-idle"}`}
          role="status"
        >
          {loading ? (
            <>
              <span
                className="report-awaiting-spinner"
                aria-hidden="true"
              />
              <strong>报告加载中</strong>
              <small>正在恢复已生成的分析结果。</small>
            </>
          ) : (
            <>
              <div className="report-empty-preview" aria-hidden="true">
                <div className="report-empty-sheet">
                  <div className="report-empty-sheet-head"><i /><i /></div>
                  <div className="report-empty-kpis"><i /><i /><i /></div>
                  <svg
                    className="report-empty-chart"
                    viewBox="0 0 260 92"
                    preserveAspectRatio="none"
                  >
                    <path d="M0 76H260M0 48H260M0 20H260" />
                    <polyline points="4,72 44,62 82,67 126,39 166,48 208,24 256,14" />
                    <circle cx="126" cy="39" r="3" />
                    <circle cx="208" cy="24" r="3" />
                    <circle cx="256" cy="14" r="3" />
                  </svg>
                  <div className="report-empty-table"><i /><i /><i /><i /></div>
                </div>
                <span className="report-empty-accent accent-one" />
                <span className="report-empty-accent accent-two" />
              </div>
              <strong>你的下一次分析，在这里。</strong>
              <small>指标、图表和明细会随着分析结果在这里展开。</small>
            </>
          )}
        </div>
      </section>
    );
  }

  return (
    <section className="report-panel" aria-label="分析结果">
      <header className="result-panel-header">
        <div>
          <span className="result-kicker">REPORT</span>
          <h2>{initialReport.title}</h2>
          <p>{taskTitle} · {initialReport.subtitle}</p>
        </div>
      </header>
      <ReportProvider report={initialReport}>
        <div className="report-canvas">
          <Render
            config={reportPuckConfig}
            data={initialReport.layout}
          />
        </div>
      </ReportProvider>
    </section>
  );
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function reportGridColumn(value: unknown): string {
  const span = typeof value === "number" ? Math.floor(value) : 12;
  return span >= 1 && span < 12 ? `span ${span}` : "1 / -1";
}
