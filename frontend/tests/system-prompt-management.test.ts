import { describe, expect, test } from "vitest";

import {
  InMemorySystemPromptRepository,
  SystemPromptManagementService,
  type SystemPromptVersion,
} from "@/modules/system/server/system-prompt-management";

function version(overrides: Partial<SystemPromptVersion> = {}): SystemPromptVersion {
  return {
    id: "prompt-v1",
    promptKey: "analysis_system",
    name: "分析系统提示词",
    description: "控制分析任务的基础行为",
    version: 1,
    content: "只输出已经核验的分析结论。",
    status: "published",
    createdById: "admin-1",
    createdAt: new Date("2026-08-01T00:00:00.000Z"),
    publishedAt: new Date("2026-08-01T00:00:00.000Z"),
    ...overrides,
  };
}

describe("system prompt management", () => {
  test("creates an immutable draft with the next version number", async () => {
    const repository = new InMemorySystemPromptRepository([version()]);
    const service = new SystemPromptManagementService(repository);

    const draft = await service.createDraft("admin-1", {
      promptKey: "analysis_system",
      name: "分析系统提示词",
      description: "控制分析任务的基础行为",
      content: "先核验数据，再输出结论。",
    });

    expect(draft).toMatchObject({
      version: 2,
      status: "draft",
      content: "先核验数据，再输出结论。",
    });
    expect((await repository.get("prompt-v1"))?.status).toBe("published");
  });

  test("publishes one version and archives the previously published version", async () => {
    const repository = new InMemorySystemPromptRepository([
      version(),
      version({
        id: "prompt-v2",
        version: 2,
        content: "新提示词",
        status: "draft",
        publishedAt: null,
      }),
    ]);
    const service = new SystemPromptManagementService(repository);

    const published = await service.publish("admin-1", "prompt-v2");

    expect(published.status).toBe("published");
    expect((await repository.get("prompt-v1"))?.status).toBe("archived");
    expect(await service.getPublishedContent("analysis_system", "fallback")).toBe("新提示词");
  });

  test("rolls back by creating a new published version without changing history", async () => {
    const repository = new InMemorySystemPromptRepository([
      version({ status: "archived" }),
      version({
        id: "prompt-v2",
        version: 2,
        content: "有问题的新提示词",
      }),
    ]);
    const service = new SystemPromptManagementService(repository);

    const rollback = await service.rollback("admin-1", "prompt-v1");

    expect(rollback).toMatchObject({
      version: 3,
      content: "只输出已经核验的分析结论。",
      status: "published",
    });
    expect((await repository.get("prompt-v1"))?.status).toBe("archived");
    expect((await repository.get("prompt-v2"))?.status).toBe("archived");
  });

  test("uses the built-in prompt when no version has been published", async () => {
    const service = new SystemPromptManagementService(
      new InMemorySystemPromptRepository([]),
    );

    expect(await service.getPublishedContent("analysis_system", "built-in")).toBe(
      "built-in",
    );
  });
});
