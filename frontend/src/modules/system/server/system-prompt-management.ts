export type SystemPromptStatus = "draft" | "published" | "archived";

export type SystemPromptVersion = {
  id: string;
  promptKey: string;
  name: string;
  description: string | null;
  version: number;
  content: string;
  status: SystemPromptStatus;
  createdById: string;
  createdAt: Date;
  publishedAt: Date | null;
};

export type SystemPromptDraftInput = {
  promptKey: string;
  name: string;
  description?: string | null;
  content: string;
};

export interface SystemPromptRepository {
  list(promptKey?: string): Promise<SystemPromptVersion[]>;
  get(versionId: string): Promise<SystemPromptVersion | null>;
  create(
    input: Omit<SystemPromptVersion, "id" | "createdAt">,
  ): Promise<SystemPromptVersion>;
  archivePublished(promptKey: string): Promise<void>;
  markPublished(versionId: string, publishedAt: Date): Promise<SystemPromptVersion>;
}

export class SystemPromptManagementError extends Error {
  constructor(
    public readonly code:
      | "prompt_content_required"
      | "prompt_key_required"
      | "prompt_version_not_found",
  ) {
    super(code);
    this.name = "SystemPromptManagementError";
  }
}

export class SystemPromptManagementService {
  constructor(private readonly repository: SystemPromptRepository) {}

  async list(promptKey?: string): Promise<SystemPromptVersion[]> {
    return this.repository.list(promptKey);
  }

  async createDraft(
    actorId: string,
    input: SystemPromptDraftInput,
  ): Promise<SystemPromptVersion> {
    const promptKey = input.promptKey.trim();
    const content = input.content.trim();
    if (!promptKey) throw new SystemPromptManagementError("prompt_key_required");
    if (!content) throw new SystemPromptManagementError("prompt_content_required");
    const versions = await this.repository.list(promptKey);
    const nextVersion = Math.max(0, ...versions.map((entry) => entry.version)) + 1;
    return this.repository.create({
      promptKey,
      name: input.name.trim() || promptKey,
      description: input.description?.trim() || null,
      version: nextVersion,
      content,
      status: "draft",
      createdById: actorId,
      publishedAt: null,
    });
  }

  async publish(actorId: string, versionId: string): Promise<SystemPromptVersion> {
    void actorId;
    const selected = await this.requireVersion(versionId);
    await this.repository.archivePublished(selected.promptKey);
    return this.repository.markPublished(selected.id, new Date());
  }

  async rollback(actorId: string, versionId: string): Promise<SystemPromptVersion> {
    const selected = await this.requireVersion(versionId);
    const draft = await this.createDraft(actorId, {
      promptKey: selected.promptKey,
      name: selected.name,
      description: selected.description,
      content: selected.content,
    });
    return this.publish(actorId, draft.id);
  }

  async getPublishedContent(promptKey: string, fallback: string): Promise<string> {
    const published = (await this.repository.list(promptKey)).find(
      (entry) => entry.status === "published",
    );
    return published?.content || fallback;
  }

  private async requireVersion(versionId: string): Promise<SystemPromptVersion> {
    const version = await this.repository.get(versionId);
    if (!version) throw new SystemPromptManagementError("prompt_version_not_found");
    return version;
  }
}

function clone(version: SystemPromptVersion): SystemPromptVersion {
  return {
    ...version,
    createdAt: new Date(version.createdAt),
    publishedAt: version.publishedAt ? new Date(version.publishedAt) : null,
  };
}

export class InMemorySystemPromptRepository implements SystemPromptRepository {
  private readonly versions: SystemPromptVersion[];

  constructor(versions: SystemPromptVersion[]) {
    this.versions = versions.map(clone);
  }

  async list(promptKey?: string): Promise<SystemPromptVersion[]> {
    return this.versions
      .filter((version) => !promptKey || version.promptKey === promptKey)
      .sort((left, right) => right.version - left.version)
      .map(clone);
  }

  async get(versionId: string): Promise<SystemPromptVersion | null> {
    const version = this.versions.find((entry) => entry.id === versionId);
    return version ? clone(version) : null;
  }

  async create(
    input: Omit<SystemPromptVersion, "id" | "createdAt">,
  ): Promise<SystemPromptVersion> {
    const created = {
      ...input,
      id: `prompt-${this.versions.length + 1}`,
      createdAt: new Date(),
    };
    this.versions.push(created);
    return clone(created);
  }

  async archivePublished(promptKey: string): Promise<void> {
    for (const version of this.versions) {
      if (version.promptKey === promptKey && version.status === "published") {
        version.status = "archived";
      }
    }
  }

  async markPublished(
    versionId: string,
    publishedAt: Date,
  ): Promise<SystemPromptVersion> {
    const version = this.versions.find((entry) => entry.id === versionId);
    if (!version) throw new SystemPromptManagementError("prompt_version_not_found");
    version.status = "published";
    version.publishedAt = publishedAt;
    return clone(version);
  }
}
