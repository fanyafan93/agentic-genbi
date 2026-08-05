"use client";

import { ListTable } from "@visactor/react-vtable";
import { useReportContext } from "./ReportContext";

export function buildVTableOption(
  options: Record<string, unknown>,
  rows: Array<Record<string, unknown>>,
): Record<string, unknown> & {
  records: Array<Record<string, unknown>>;
} {
  return {
    ...options,
    records: rows,
  };
}

export function ReportTable({ tableId }: { tableId: string }) {
  const { report, queryStates, executeQuery } = useReportContext();
  const table = report.tables[tableId];
  if (!table) {
    return (
      <div className="report-query-error" role="alert">
        未找到表格配置：{tableId}
      </div>
    );
  }
  const state = queryStates[table.queryId];
  if (!state || state.loading) {
    return <div className="report-query-loading">表格加载中…</div>;
  }
  if (state.error) {
    return (
      <div className="report-query-error" role="alert">
        <span>{state.error}</span>
        <button
          type="button"
          onClick={() => void executeQuery(
            table.queryId,
            state.page,
            state.pageSize,
          )}
        >
          重试
        </button>
      </div>
    );
  }

  const option = buildVTableOption(table.options, state.rows);
  const query = report.queries[table.queryId];
  const lastPage = Math.max(
    1,
    Math.ceil(state.total / state.pageSize),
  );
  return (
    <>
      <ListTable option={option} />
      {query?.pagination ? (
        <div className="report-table-pagination">
          <button
            type="button"
            disabled={state.page <= 1}
            onClick={() => void executeQuery(
              table.queryId,
              state.page - 1,
              state.pageSize,
            )}
          >
            上一页
          </button>
          <span>{state.page} / {lastPage}</span>
          <button
            type="button"
            disabled={state.page >= lastPage}
            onClick={() => void executeQuery(
              table.queryId,
              state.page + 1,
              state.pageSize,
            )}
          >
            下一页
          </button>
        </div>
      ) : null}
    </>
  );
}
