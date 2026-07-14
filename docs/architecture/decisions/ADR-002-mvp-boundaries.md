# ADR-002: Keep MVP infrastructure and data boundaries minimal

- Status: Accepted
- Date: 2026-07-14
- Decision owners: Project technical lead

## Context

The MVP is intended to validate one complete natural-language analytics loop, not a general BI platform. The highest-risk unknowns are safe SQL execution, useful metadata discovery, bounded repair, and understandable report output. Infrastructure for scale, tenancy, durable jobs, and semantic modeling does not reduce those initial risks.

## Decision

The first version will:

- connect to exactly one MySQL test or desensitized database;
- use a dedicated read-only MySQL account and configured schema/table allowlists;
- keep task state in one FastAPI process and expose polling;
- use one analysis Agent;
- generate the report as validated structured Agent output;
- run locally with Docker Compose.

The first version will not use Redis, Celery, WrenAI, LangGraph, multi-tenancy, a vector database, Kubernetes, MinIO, or a generic multi-database connector layer.

## Rationale

### One MySQL database

- It matches the confirmed first data source.
- It allows SQL parsing, metadata, timeout, and read-only permissions to be designed for one dialect and tested deeply.
- A generic connector interface before a second real database would encode guesses and weaken safety.

### No Redis or Celery

- Local process tasks and polling satisfy the accepted MVP user experience.
- No acceptance criterion requires restart survival, horizontal workers, scheduling, or long-running queues.
- Queue infrastructure would add serialization, worker lifecycle, retries, result storage, and operational failure modes.

### No WrenAI

- The MVP must first learn whether schema metadata plus one Agent can answer the fixed questions safely.
- A semantic layer introduces modeling and synchronization work before a recurring semantic problem has been measured.
- Report assumptions and known limitations make current semantic gaps visible.

### No multi-tenancy

- The MVP uses one controlled database and has no production identity system.
- Tenant isolation is a security architecture, not a UI flag; implementing it partially would create false confidence.

## Consequences

### Benefits

- Small architecture with clear trust boundaries.
- Faster delivery of the complete vertical loop.
- Security testing can focus on one SQL dialect and permission model.
- Failures are easier to reproduce locally.

### Costs and accepted limitations

- Tasks and results disappear on backend restart.
- Only one backend worker/process is supported.
- One configured database serves all local users.
- Business terminology is limited to metadata/comments and Agent instructions.
- Adding a second database or real tenancy will require deliberate interface and migration work.

## Introduction triggers

### Redis/durable result storage

Introduce when tasks must survive restart, multiple API workers must share status, task history must be retained, or measured memory usage requires eviction/persistence.

### Celery or another job queue

Introduce after durable storage is justified and background runs need independent workers, queue backpressure, scheduled execution, or operational retries. Do not introduce Celery solely to make HTTP asynchronous.

### WrenAI or another semantic layer

Evaluate when fixed questions repeatedly fail because business metrics, joins, or naming cannot be captured reliably through schema comments and concise context, and the team can own semantic-model lifecycle and validation.

### Multi-tenancy and production authentication

Introduce before serving multiple untrusted users, organizations, or datasets. The design must cover identity, tenant-scoped credentials, authorization, audit, deletion, and isolation tests together.

### Multiple databases

Introduce only when a second concrete data source has acceptance scenarios. Define a narrow connector contract from both working implementations rather than predicting it now.

## Rejected shortcuts

- Treating prompt instructions as database authorization.
- Storing tenant IDs without enforcing isolation throughout data access.
- Adding unused abstractions named for future databases.
- Running multiple FastAPI workers while retaining process-local task state.

Any boundary change requires an ADR and updates to scope, interfaces, tests, README, and handoff documentation.
