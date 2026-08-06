import type { CSSProperties, ReactNode } from "react";
import type { Report } from "../types/report";

type CoverBlock = {
  type?: unknown;
  props?: Record<string, unknown>;
};

const CHART_KINDS = new Set([
  "bar",
  "line",
  "pie",
  "radar",
  "gauge",
  "funnel",
]);

export function ReportCover({ report }: { report: Report }) {
  const content = Array.isArray(report.layout.content)
    ? report.layout.content as unknown as CoverBlock[]
    : [];

  return (
    <div className="report-cover" aria-label={`${report.title} 报表封面`}>
      <div className="report-cover-grid">
        {content.length > 0 ? content.map((block, index) => (
          <CoverBlockView
            key={coverBlockKey(block, index)}
            block={block}
            report={report}
          />
        )) : <GenericBlock label="空白报表" />}
      </div>
    </div>
  );
}

function CoverBlockView({ block, report }: { block: CoverBlock; report: Report }) {
  const props = asObject(block.props);
  const type = typeof block.type === "string" ? block.type : "";
  const columnSpan = normalizedColumnSpan(props.columnSpan);
  const style: CSSProperties = { gridColumn: `span ${columnSpan}` };

  if (type === "FilterBlock") {
    const filterIds = Array.isArray(props.filterIds) ? props.filterIds.map(String) : [];
    const labels = filterIds
      .map((filterId) => report.filters[filterId]?.label)
      .filter((label): label is string => Boolean(label));
    return (
      <div className="report-cover-block is-filter" data-testid="report-cover-filter" style={style}>
        {(labels.length ? labels : ["筛选条件"]).slice(0, 3).map((label) => (
          <span key={label}><i />{label}</span>
        ))}
      </div>
    );
  }

  if (type === "ChartBlock") {
    const chartId = String(props.chartId ?? "chart");
    const chartKind = reportChartKind(report, chartId);
    return (
      <div
        className={`report-cover-block is-chart is-${chartKind}`}
        data-chart-kind={chartKind}
        data-testid={`report-cover-chart-${chartId}`}
        style={style}
      >
        <ChartGlyph kind={chartKind} />
      </div>
    );
  }

  if (type === "TableBlock") {
    return (
      <div className="report-cover-block is-table" data-testid="report-cover-table" style={style}>
        <i /><i /><i /><i />
      </div>
    );
  }

  if (type === "SectionBlock") {
    return (
      <div className="report-cover-block is-section" style={style}>
        <strong>{String(props.title ?? "报表分区")}</strong>
      </div>
    );
  }

  if (type === "MarkdownBlock") {
    return (
      <div className="report-cover-block is-copy" style={style}>
        <i /><i /><i />
      </div>
    );
  }

  return <GenericBlock label="内容" style={style} />;
}

function ChartGlyph({ kind }: { kind: string }) {
  let marks: ReactNode;
  if (kind === "bar") {
    marks = <><rect x="14" y="31" width="10" height="22" /><rect x="31" y="19" width="10" height="34" /><rect x="48" y="26" width="10" height="27" /><rect x="65" y="11" width="10" height="42" /></>;
  } else if (kind === "pie") {
    marks = <><circle cx="45" cy="31" r="20" /><path d="M45 31V11A20 20 0 0 1 64 38Z" /></>;
  } else if (kind === "radar") {
    marks = <><path d="M45 8 73 26 62 55 28 55 17 26Z" /><path d="M45 17 62 28 56 46 34 48 26 29Z" /></>;
  } else if (kind === "gauge") {
    marks = <><path d="M18 47A28 28 0 0 1 72 47" /><path d="m45 45 17-18" /><circle cx="45" cy="45" r="4" /></>;
  } else if (kind === "funnel") {
    marks = <><path d="M12 12H78L66 25H24Z" /><path d="M25 29H65L57 41H33Z" /><path d="M34 45H56L51 55H39Z" /></>;
  } else {
    marks = <><polyline points="8,49 24,35 39,41 54,20 70,26 82,11" /><circle cx="54" cy="20" r="2.5" /><circle cx="82" cy="11" r="2.5" /></>;
  }
  return <svg viewBox="0 0 90 62" aria-hidden="true">{marks}</svg>;
}

function GenericBlock({ label, style }: { label: string; style?: CSSProperties }) {
  return <div className="report-cover-block is-generic" style={style}><span>{label}</span><i /></div>;
}

function reportChartKind(report: Report, chartId: string): string {
  const option = asObject(report.charts[chartId]?.option);
  const series = Array.isArray(option.series) ? option.series : [];
  for (const item of series) {
    const kind = asObject(item).type;
    if (typeof kind === "string" && CHART_KINDS.has(kind)) return kind;
  }
  return "generic";
}

function normalizedColumnSpan(value: unknown): number {
  const span = typeof value === "number" ? Math.floor(value) : 12;
  return Math.min(12, Math.max(1, span));
}

function coverBlockKey(block: CoverBlock, index: number): string {
  const id = asObject(block.props).id;
  return typeof id === "string" && id ? id : `${String(block.type ?? "block")}-${index}`;
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
