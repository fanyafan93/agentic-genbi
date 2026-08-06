"use client";

import { ListTable, PivotTable } from "@visactor/react-vtable";
import type { BaseTableAPI } from "@visactor/vtable";
import { Select } from "antd";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type {
  ReportColumnFilters,
  ReportSort,
} from "../types/report";
import { exportReportTable } from "../api/report-service";
import { useReportContext } from "./ReportContext";

type VTableControlState = {
  sort: ReportSort | null;
  columnFilters: ReportColumnFilters;
};

type HeaderMenuEvent = {
  field?: unknown;
  menuKey?: unknown;
};

export function buildVTableOption(
  options: Record<string, unknown>,
  rows: Array<Record<string, unknown>>,
  controls: VTableControlState = {
    sort: null,
    columnFilters: {},
  },
): Record<string, unknown> & {
  records: Array<Record<string, unknown>>;
} {
  const columns = Array.isArray(options.columns)
    ? options.columns.map((value) => {
      const column = asObject(value);
      const field = typeof column.field === "string"
        ? column.field
        : "";
      const menuItems = buildColumnMenu(column);
      return {
        ...column,
        ...(menuItems.length ? { dropDownMenu: menuItems } : {}),
        ...(controls.sort?.field === field
          ? { sort: controls.sort.direction }
          : {}),
      };
    })
    : [];
  const theme = asObject(options.theme);
  const scrollStyle = asObject(theme.scrollStyle);
  const menu = asObject(options.menu);
  const dropDownMenuHighlight = buildMenuHighlights(controls);
  return {
    ...options,
    columns,
    widthMode: "standard",
    theme: {
      ...theme,
      scrollStyle: {
        ...scrollStyle,
        horizontalVisible: "none",
        verticalVisible: "none",
        barToSide: true,
        width: 8,
      },
    },
    menu: {
      ...menu,
      dropDownMenuHighlight,
    },
    records: rows,
  };
}

export function ReportTable({ tableId }: { tableId: string }) {
  const {
    report,
    filterValues,
    queryStates,
    executeQuery,
  } = useReportContext();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const table = report.tables[tableId];
  if (!table) {
    return (
      <div className="report-query-error" role="alert">
        未找到表格配置：{tableId}
      </div>
    );
  }
  const state = queryStates[table.queryId];
  if (!state || (state.loading && state.rows.length === 0)) {
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

  const option = buildVTableOption(
    table.options,
    state.rows,
    {
      sort: state.sort,
      columnFilters: state.columnFilters,
    },
  );
  const query = report.queries[table.queryId];
  const canExport = (
    !report.buildId
    && table.type !== "pivot"
    && Array.isArray(table.exportColumns)
    && table.exportColumns.length > 0
  );
  const tableHeight = positiveNumber(table.options.height, 360);
  const tableOption = { ...option };
  delete tableOption.height;
  const lastPage = Math.max(
    1,
    Math.ceil(state.total / state.pageSize),
  );
  const refreshAfterHeaderMenu = (
    controls: {
      sort: ReportSort | null;
      columnFilters: ReportColumnFilters;
    },
  ) => {
    window.setTimeout(() => {
      void executeQuery(
        table.queryId,
        1,
        state.pageSize,
        controls,
      );
    }, 0);
  };
  const handleHeaderMenu = (event: HeaderMenuEvent) => {
    const field = typeof event.field === "string" ? event.field : "";
    const menuKey = typeof event.menuKey === "string"
      ? event.menuKey
      : "";
    if (!field || !menuKey) return;
    if (menuKey.startsWith("sort:")) {
      const direction = menuKey.slice(5);
      const nextSort = direction === "asc" || direction === "desc"
        ? { field, direction } as ReportSort
        : null;
      refreshAfterHeaderMenu({
        sort: nextSort,
        columnFilters: state.columnFilters,
      });
      return;
    }
    if (menuKey === "filter:clear") {
      const nextFilters = { ...state.columnFilters };
      delete nextFilters[field];
      refreshAfterHeaderMenu({
        sort: state.sort,
        columnFilters: nextFilters,
      });
      return;
    }
    if (menuKey.startsWith("filter:")) {
      const value = decodeURIComponent(menuKey.slice(7));
      const selected = new Set(state.columnFilters[field] ?? []);
      if (selected.has(value)) {
        selected.delete(value);
      } else {
        selected.add(value);
      }
      const nextFilters = {
        ...state.columnFilters,
        [field]: [...selected],
      };
      if (!nextFilters[field].length) delete nextFilters[field];
      refreshAfterHeaderMenu({
        sort: state.sort,
        columnFilters: nextFilters,
      });
    }
  };
  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const exported = await exportReportTable(
        report.id,
        tableId,
        {
          filters: filterValues,
          sort: state.sort,
          columnFilters: state.columnFilters,
        },
      );
      downloadBlob(exported.blob, exported.filename);
    } catch (error) {
      setExportError(
        error instanceof Error ? error.message : "Excel 导出失败",
      );
    } finally {
      setExporting(false);
    }
  };
  return (
    <>
      {canExport ? (
        <div className="report-table-toolbar">
          {exportError ? (
            <span role="alert">导出失败，请稍后重试</span>
          ) : null}
          <button
            type="button"
            disabled={exporting}
            onClick={() => void handleExport()}
          >
            {exporting ? "正在生成…" : "导出 Excel"}
          </button>
        </div>
      ) : null}
      <div
        className="report-table-stage"
        aria-busy={state.loading}
      >
        <ReportVTable
          type={table.type}
          option={tableOption}
          height={tableHeight}
          onDropdownMenuClick={handleHeaderMenu}
        />
        {state.loading ? (
          <div className="report-table-refreshing" role="status">
            正在加载第 {state.page} 页…
          </div>
        ) : null}
      </div>
      {query?.pagination ? (
        <div className="report-table-pagination">
          <Select
            aria-label="每页条数"
            className="report-page-size-select"
            value={state.pageSize}
            disabled={state.loading}
            options={[
              { label: "20 条/页", value: 20 },
              { label: "50 条/页", value: 50 },
              { label: "100 条/页", value: 100 },
            ]}
            onChange={(pageSize) => void executeQuery(
              table.queryId,
              1,
              pageSize,
              {
                sort: state.sort,
                columnFilters: state.columnFilters,
              },
            )}
          />
          <button
            type="button"
            disabled={state.loading || state.page <= 1}
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
            disabled={state.loading || state.page >= lastPage}
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

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function ReportVTable({
  type,
  option,
  height,
  onDropdownMenuClick,
}: {
  type?: "list" | "pivot";
  option: Record<string, unknown>;
  height: number;
  onDropdownMenuClick: (event: HeaderMenuEvent) => void;
}) {
  const [instance, setInstance] = useState<BaseTableAPI | null>(null);
  const handleReady = useCallback((readyInstance: unknown) => {
    setInstance(readyInstance as BaseTableAPI);
  }, []);

  return (
    <>
      {type === "pivot" ? (
        <PivotTable
          option={option}
          height={height}
          onReady={handleReady}
        />
      ) : (
        <ListTable
          option={option}
          height={height}
          onDropdownMenuClick={onDropdownMenuClick}
          onReady={handleReady}
        />
      )}
      <NativeTableScrollbars
        instance={instance}
        option={option}
      />
    </>
  );
}

function NativeTableScrollbars({
  instance,
  option,
}: {
  instance: BaseTableAPI | null;
  option: Record<string, unknown>;
}) {
  const horizontalRef = useRef<HTMLDivElement>(null);
  const verticalRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);
  const records = Array.isArray(option.records)
    ? option.records
    : [];
  const configuredWidth = configuredColumnsWidth(option);
  const [contentSize, setContentSize] = useState({
    width: 1,
    height: 1,
  });

  useEffect(() => {
    if (!instance) return;

    const refreshSize = () => {
      setContentSize({
        width: Math.max(
          1,
          configuredWidth,
          instance.getAllColsWidth(),
        ),
        height: Math.max(1, instance.getAllRowsHeight()),
      });
      if (horizontalRef.current) {
        horizontalRef.current.scrollLeft = instance.scrollLeft;
      }
      if (verticalRef.current) {
        verticalRef.current.scrollTop = instance.scrollTop;
      }
    };
    refreshSize();
    const listenerId = instance.on(
      "scroll",
      (event) => {
        syncingRef.current = true;
        setContentSize((current) => ({
          width: Math.max(
            current.width,
            1,
            configuredWidth,
            event.scrollWidth,
          ),
          height: Math.max(
            current.height,
            1,
            event.scrollHeight,
          ),
        }));
        if (horizontalRef.current) {
          horizontalRef.current.scrollLeft = event.scrollLeft;
        }
        if (verticalRef.current) {
          verticalRef.current.scrollTop = event.scrollTop;
        }
        window.requestAnimationFrame(() => {
          syncingRef.current = false;
        });
      },
    );
    return () => {
      instance.off(listenerId);
    };
  }, [configuredWidth, instance, records.length]);

  return (
    <>
      <div
        ref={horizontalRef}
        className={
          "report-table-native-scrollbar " +
          "report-table-native-scrollbar-horizontal"
        }
        aria-label="table horizontal scrollbar"
        onScroll={(event) => {
          if (!instance || syncingRef.current) return;
          instance.scrollLeft = event.currentTarget.scrollLeft;
        }}
      >
        <div style={{ width: contentSize.width }} />
      </div>
      <div
        ref={verticalRef}
        className={
          "report-table-native-scrollbar " +
          "report-table-native-scrollbar-vertical"
        }
        aria-label="table vertical scrollbar"
        onScroll={(event) => {
          if (!instance || syncingRef.current) return;
          instance.scrollTop = event.currentTarget.scrollTop;
        }}
      >
        <div style={{ height: contentSize.height }} />
      </div>
    </>
  );
}

function configuredColumnsWidth(
  option: Record<string, unknown>,
): number {
  if (!Array.isArray(option.columns)) return 0;
  return option.columns.reduce((total, value) => {
    const column = asObject(value);
    if (Array.isArray(column.columns)) {
      return total + configuredColumnsWidth(column);
    }
    return total + positiveNumber(column.width, 120);
  }, 0);
}

function buildColumnMenu(
  column: Record<string, unknown>,
): Array<Record<string, unknown>> {
  const menu: Array<Record<string, unknown>> = [];
  if (column.sortable === true) {
    menu.push(
      { text: "升序", menuKey: "sort:asc" },
      { text: "降序", menuKey: "sort:desc" },
      { text: "清除排序", menuKey: "sort:clear" },
    );
  }
  const filterOptions = Array.isArray(column.filterOptions)
    ? column.filterOptions
    : [];
  if (filterOptions.length) {
    if (menu.length) menu.push({ type: "split" });
    for (const value of filterOptions) {
      const option = asObject(value);
      if (
        typeof option.label === "string"
        && typeof option.value === "string"
      ) {
        menu.push({
          text: option.label,
          menuKey: `filter:${encodeURIComponent(option.value)}`,
        });
      }
    }
    menu.push({ text: "清除筛选", menuKey: "filter:clear" });
  }
  return menu;
}

function buildMenuHighlights(
  controls: VTableControlState,
): Array<Record<string, string>> {
  const highlights: Array<Record<string, string>> = [];
  if (controls.sort) {
    highlights.push({
      field: controls.sort.field,
      menuKey: `sort:${controls.sort.direction}`,
    });
  }
  for (const [field, values] of Object.entries(
    controls.columnFilters,
  )) {
    for (const value of values) {
      highlights.push({
        field,
        menuKey: `filter:${encodeURIComponent(value)}`,
      });
    }
  }
  return highlights;
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function positiveNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : fallback;
}
