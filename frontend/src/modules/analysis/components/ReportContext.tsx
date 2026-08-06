"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  executeReportBuildQuery,
  executeReportQuery,
} from "../api/report-service";
import type {
  ReportColumnFilters,
  Report,
  ReportFilterValue,
  ReportQueryResult,
  ReportSort,
} from "../types/report";

export type QueryState = {
  columns: ReportQueryResult["columns"];
  rows: ReportQueryResult["rows"];
  total: number;
  page: number;
  pageSize: number;
  sort: ReportSort | null;
  columnFilters: ReportColumnFilters;
  loading: boolean;
  error: string | null;
};

export type QueryControlUpdate = {
  sort?: ReportSort | null;
  columnFilters?: ReportColumnFilters;
};

type ReportRuntimeContext = {
  report: Report;
  filterValues: Record<string, ReportFilterValue>;
  queryStates: Record<string, QueryState>;
  setFilterValue(
    filterId: string,
    value: ReportFilterValue,
  ): void;
  executeQuery(
    queryId: string,
    page?: number,
    pageSize?: number,
    controls?: QueryControlUpdate,
  ): Promise<void>;
};

const ReportContext = createContext<ReportRuntimeContext | null>(null);

export function ReportProvider({
  report,
  children,
}: {
  report: Report;
  children: ReactNode;
}) {
  const initialFilterValues = useMemo(
    () => Object.fromEntries(
      Object.entries(report.filters).map(([filterId, definition]) => [
        filterId,
        definition.defaultValue ?? null,
      ]),
    ),
    [report.filters],
  );
  const referencedQueryIds = useMemo(
    () => collectReferencedQueryIds(report),
    [report],
  );
  const referencedQueryKey = referencedQueryIds.join("\u0000");
  const [filterValues, setFilterValues] = useState<
    Record<string, ReportFilterValue>
  >(initialFilterValues);
  const [queryStates, setQueryStates] = useState<
    Record<string, QueryState>
  >(() => Object.fromEntries(
    referencedQueryIds.map((queryId) => [
      queryId,
      emptyQueryState(),
    ]),
  ));

  const performQuery = useCallback(
    async (
      queryId: string,
      values: Record<string, ReportFilterValue>,
      page = 1,
      pageSize = 50,
      sort: ReportSort | null = null,
      columnFilters: ReportColumnFilters = {},
    ) => {
      setQueryStates((current) => ({
        ...current,
        [queryId]: {
          ...(current[queryId] ?? emptyQueryState()),
          page,
          pageSize,
          sort,
          columnFilters,
          loading: true,
          error: null,
        },
      }));
      try {
        const request = {
          filters: values,
          page,
          pageSize,
          sort,
          columnFilters,
        };
        const result = report.buildId
          ? await executeReportBuildQuery(
              report.buildId,
              queryId,
              request,
            )
          : await executeReportQuery(
              report.id,
              queryId,
              request,
            );
        setQueryStates((current) => ({
          ...current,
          [queryId]: {
            ...result,
            sort,
            columnFilters,
            loading: false,
            error: null,
          },
        }));
      } catch (error) {
        setQueryStates((current) => ({
          ...current,
          [queryId]: {
            ...(current[queryId] ?? emptyQueryState()),
            page,
            pageSize,
            sort,
            columnFilters,
            loading: false,
            error: error instanceof Error
              ? error.message
              : "Report query failed.",
          },
        }));
      }
    },
    [report.id],
  );

  useEffect(() => {
    setFilterValues(initialFilterValues);
    setQueryStates(Object.fromEntries(
      referencedQueryIds.map((queryId) => [
        queryId,
        emptyQueryState(),
      ]),
    ));
    for (const queryId of referencedQueryIds) {
      void performQuery(queryId, initialFilterValues);
    }
    // referencedQueryKey is the stable value contract for the layout.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    report.id,
    referencedQueryKey,
    initialFilterValues,
    performQuery,
  ]);

  const executeQuery = useCallback(
    async (
      queryId: string,
      page?: number,
      pageSize?: number,
      controls?: QueryControlUpdate,
    ) => {
      const current = queryStates[queryId] ?? emptyQueryState();
      await performQuery(
        queryId,
        filterValues,
        page ?? current.page,
        pageSize ?? current.pageSize,
        controls?.sort !== undefined
          ? controls.sort
          : current.sort,
        controls?.columnFilters ?? current.columnFilters,
      );
    },
    [filterValues, performQuery, queryStates],
  );

  const setFilterValue = useCallback(
    (filterId: string, value: ReportFilterValue) => {
      const nextValues = { ...filterValues, [filterId]: value };
      setFilterValues(nextValues);
      for (const queryId of referencedQueryIds) {
        const query = report.queries[queryId];
        const isBound = Object.values(
          query?.parameters ?? {},
        ).some((parameter) => parameter.filterId === filterId);
        if (isBound) {
          const current = queryStates[queryId] ?? emptyQueryState();
          void performQuery(
            queryId,
            nextValues,
            1,
            current.pageSize,
            current.sort,
            current.columnFilters,
          );
        }
      }
    },
    [
      filterValues,
      performQuery,
      referencedQueryIds,
      report.queries,
      queryStates,
    ],
  );

  const value = useMemo(
    () => ({
      report,
      filterValues,
      queryStates,
      setFilterValue,
      executeQuery,
    }),
    [
      executeQuery,
      filterValues,
      queryStates,
      report,
      setFilterValue,
    ],
  );

  return (
    <ReportContext.Provider value={value}>
      {children}
    </ReportContext.Provider>
  );
}

export function useReportContext(): ReportRuntimeContext {
  const context = useContext(ReportContext);
  if (!context) {
    throw new Error(
      "useReportContext must be used inside ReportProvider.",
    );
  }
  return context;
}

function emptyQueryState(): QueryState {
  return {
    columns: [],
    rows: [],
    total: 0,
    page: 1,
    pageSize: 50,
    sort: null,
    columnFilters: {},
    loading: false,
    error: null,
  };
}

function collectReferencedQueryIds(report: Report): string[] {
  const queryIds = new Set<string>();
  visitLayoutNodes(report.layout.content, report, queryIds);
  visitLayoutNodes(report.layout.zones, report, queryIds);
  return [...queryIds];
}

function visitLayoutNodes(
  value: unknown,
  report: Report,
  queryIds: Set<string>,
): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      visitLayoutNodes(item, report, queryIds);
    }
    return;
  }
  if (!isObject(value)) {
    return;
  }
  const props = isObject(value.props) ? value.props : {};
  if (typeof props.chartId === "string") {
    const queryId = report.charts[props.chartId]?.queryId;
    if (queryId) queryIds.add(queryId);
  }
  if (typeof props.tableId === "string") {
    const queryId = report.tables[props.tableId]?.queryId;
    if (queryId) queryIds.add(queryId);
  }
  for (const nested of Object.values(value)) {
    visitLayoutNodes(nested, report, queryIds);
  }
}

function isObject(
  value: unknown,
): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object"
    && !Array.isArray(value);
}
