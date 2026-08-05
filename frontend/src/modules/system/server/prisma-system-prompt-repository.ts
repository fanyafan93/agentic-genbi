import type {
  Prisma,
  PrismaClient,
  SystemPromptVersion as PrismaSystemPromptVersion,
} from "@prisma/client";

import {
  SystemPromptManagementError,
  type SystemPromptRepository,
  type SystemPromptStatus,
  type SystemPromptVersion,
} from "./system-prompt-management";

type DatabaseClient = PrismaClient | Prisma.TransactionClient;

function promptStatus(value: string): SystemPromptStatus {
  if (value === "published" || value === "archived") return value;
  return "draft";
}

function managedPrompt(row: PrismaSystemPromptVersion): SystemPromptVersion {
  return {
    ...row,
    status: promptStatus(row.status),
  };
}

export class PrismaSystemPromptRepository implements SystemPromptRepository {
  constructor(private readonly database: DatabaseClient) {}

  async list(promptKey?: string): Promise<SystemPromptVersion[]> {
    const rows = await this.database.systemPromptVersion.findMany({
      where: promptKey ? { promptKey } : undefined,
      orderBy: [{ promptKey: "asc" }, { version: "desc" }],
    });
    return rows.map(managedPrompt);
  }

  async get(versionId: string): Promise<SystemPromptVersion | null> {
    const row = await this.database.systemPromptVersion.findUnique({
      where: { id: versionId },
    });
    return row ? managedPrompt(row) : null;
  }

  async create(
    input: Omit<SystemPromptVersion, "id" | "createdAt">,
  ): Promise<SystemPromptVersion> {
    return managedPrompt(
      await this.database.systemPromptVersion.create({ data: input }),
    );
  }

  async archivePublished(promptKey: string): Promise<void> {
    await this.database.systemPromptVersion.updateMany({
      where: { promptKey, status: "published" },
      data: { status: "archived" },
    });
  }

  async markPublished(
    versionId: string,
    publishedAt: Date,
  ): Promise<SystemPromptVersion> {
    try {
      return managedPrompt(
        await this.database.systemPromptVersion.update({
          where: { id: versionId },
          data: { status: "published", publishedAt },
        }),
      );
    } catch (error) {
      if (
        typeof error === "object" &&
        error !== null &&
        "code" in error &&
        error.code === "P2025"
      ) {
        throw new SystemPromptManagementError("prompt_version_not_found");
      }
      throw error;
    }
  }
}
