# Task 3 Frontend Analysis Report Implementation Plan

> For agentic workers: use the task-3 handoff and current implementation as the source of truth. Steps use checkbox syntax for tracking.

**Goal:** Use task 2's analysis-task contract to submit a question, poll the task, and render a safe fixed analysis report in the browser.

**Architecture:** A client-side `AnalysisPage` owns question, task, error, and polling state. API access is isolated in `analysis-api.ts`; report rendering is split into status, table, chart, and report-view components. Server response fields are rendered as React text, never as raw HTML or executable code.

**Tech Stack:** Next.js 16, React 19, TypeScript, Vitest, Testing Library, jsdom, CSS.

## Global Constraints

- Do not add database, OpenAI Agents SDK, SQL execution, or SQL repair behavior in task 3.
- Stop polling at `succeeded`, `failed`, or `requires_input`.
- Do not retry a missing task after a polling `404`.
- Render `chart: null` as a table-only result.

## Task 1: API Types and Client

- [x] Add the frontend representations of `AnalysisTaskStatus`, `AnalysisReport`, `ReportTable`, and `ChartSpec`.
- [x] Add `createAnalysisTask(question)` and `getAnalysisTask(taskId)` using the task 2 endpoints and structured error messages.

## Task 2: Analysis State and Report Components

- [x] Add the client page, form, task status, report view, table, and chart components.
- [x] Generate chart options locally from validated report fields and render values as React text.
- [x] Add responsive editorial-style visual treatment for desktop and mobile layouts.

## Task 3: Verification

- [x] Test blank submission rejection.
- [x] Test queued-to-succeeded polling and report rendering.
- [x] Test failed terminal state and missing-task polling behavior.
- [x] Run full frontend tests, Next.js production build, and task 2 backend regression tests.

