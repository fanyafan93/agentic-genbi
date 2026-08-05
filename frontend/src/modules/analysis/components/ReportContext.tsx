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
import { executeReportQuery } from "../api/report-service";
import type {
  Report,
  ReportFilterValue,
  ReportQueryResult,
} from "../types/report";

export type QueryState = {
  columns: ReportQueryResult["columns"];
  rows: ReportQueryResult["rows"];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  error: string | null;
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
    ) => {
      setQueryStates((current) => ({
        ...current,
        [queryId]: {
          ...(current[queryId] ?? emptyQueryState()),
          page,
          pageSize,
          loading: true,
          error: null,
        },
      }));
      try {
        const result = await executeReportQuery(
          report.id,
          queryId,
          { filters: values, page, pageSize },
        );
        setQueryStates((current) => ({
          ...current,
          [queryId]: {
            ...result,
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
    async (queryId: string, page = 1, pageSize = 50) => {
      await performQuery(
        queryId,
        filterValues,
        page,
        pageSize,
      );
    },
    [filterValues, performQuery],
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
          void performQuery(queryId, nextValues);
        }
      }
    },
    [
      filterValues,
      performQuery,
      referencedQueryIds,
      report.queries,
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
