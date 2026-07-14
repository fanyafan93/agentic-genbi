# ADR-001: Use OpenAI Agents SDK for the MVP runtime

- Status: Accepted
- Date: 2026-07-14
- Decision owners: Project technical lead

## Context

The MVP needs one analysis Agent that can inspect metadata, execute a guarded query, observe a structured SQL error, repair the query at most twice, and return a structured report. The workflow is bounded and mostly linear. Security and retry limits must remain deterministic Python concerns rather than model decisions.

The project requirements already select OpenAI Agents SDK and explicitly defer LangGraph. The prior Wren commercial design on another branch described a broader mock platform and is not the baseline for this MVP.

## Decision

Use OpenAI Agents SDK for the single Agent's model interaction, tool registration, tool selection, and final structured `AnalysisReport` output.

Use a small application-owned coordinator around the SDK to enforce:

- total tool-call and task-time budgets;
- initial SQL execution plus at most two repair retries;
- safe recording of execution steps;
- translation of tool outcomes into terminal task status;
- Pydantic validation of the final report.

Do not use LangGraph in the MVP. Do not hide the coordinator behind a generic workflow engine abstraction.

## Why this choice

- It directly supports the required single-Agent tool loop and structured output.
- It keeps the model integration smaller than introducing a graph runtime for a short workflow.
- It lets the project prove the risky parts first: SQL safety, metadata quality, repair reliability, and report usefulness.
- Application-owned limits remain visible, testable, and independent of prompts.
- It matches the confirmed technology direction and avoids an unnecessary framework comparison project.

## Why not LangGraph now

The current flow has one Agent, one database, one bounded retry loop, no durable checkpoint, no parallel branches, and no human approval stage inside a run. A graph runtime would add state modeling, persistence choices, graph-node interfaces, and another debugging surface without satisfying an MVP acceptance criterion.

Deferring LangGraph is not a claim that it is unsuitable generally. It is a YAGNI decision for this workflow.

## Consequences

### Benefits

- Fewer runtime concepts and dependencies.
- Faster onboarding and easier local debugging.
- Direct mapping from acceptance criteria to tools and coordinator tests.
- Clear separation between probabilistic reasoning and deterministic policy.

### Costs

- The coordinator contains explicit state/retry logic that a workflow engine might later provide.
- Process-local tasks cannot resume after restart.
- More complex future branching may require migration rather than configuration.
- The project depends on the selected SDK/model supporting reliable tool calls and structured output; this remains a **待验证假设** until the integration task pins versions and tests behavior.

### Risks and mitigations

- **SDK API change:** pin verified versions and isolate SDK-specific setup under `backend/app/agents/`.
- **Model loops or excess calls:** enforce budgets in the coordinator and tool wrappers.
- **Invalid report output:** require Pydantic validation and fail closed.
- **Security assumptions leaking into prompts:** keep all SQL and database controls in deterministic services and MySQL grants.

## Reconsideration triggers

Evaluate LangGraph or another durable workflow runtime only when at least one confirmed requirement appears:

- Runs must resume after process restart or wait hours/days for external input.
- Human approval must pause and continue the same run.
- Multiple specialized Agents or parallel tool branches are required.
- Workflow branching/versioning becomes difficult to test in the coordinator.
- Durable checkpoints and replay are product requirements.
- Operational evidence shows the simple coordinator is a material reliability bottleneck.

Any change requires a new ADR with migration and rollback plans.
