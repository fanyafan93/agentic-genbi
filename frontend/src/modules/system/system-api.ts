import type { SystemRuntimePolicy } from "./runtime-policy";

export type SystemAccess =
  | "administrator"
  | "bootstrap_required"
  | "forbidden"
  | "unauthenticated";

export type ManagedUser = {
  id: string;
  name: string | null;
  email: string | null;
  image: string | null;
  role: "admin" | "user";
  status: "active" | "disabled";
  createdAt: string;
  updatedAt: string;
};

export type ManagedPrompt = {
  id: string;
  promptKey: string;
  name: string;
  description: string | null;
  version: number;
  content: string;
  status: "draft" | "published" | "archived";
  createdById: string;
  createdAt: string;
  publishedAt: string | null;
};

export type RuntimeStatus = SystemRuntimePolicy & {
  provider: string;
  enabled: boolean;
  model: string;
};

export type ManagedModelProviderType =
  | "openai"
  | "minimax"
  | "openai_compatible";

export type ManagedModelConnection = {
  id: string;
  name: string;
  displayName: string;
  providerType: ManagedModelProviderType;
  model: string;
  baseUrl: string;
  enabled: boolean;
  isDefault: boolean;
  apiKeyConfigured: boolean;
  status: string;
  message: string;
  lastTestedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type ManagedModelConnectionInput = {
  name: string;
  displayName: string;
  providerType: ManagedModelProviderType;
  model: string;
  baseUrl: string;
  apiKey?: string;
  enabled: boolean;
};

export type ManagedSkill = {
  name: string;
  description: string;
  scope: "system" | "user";
};

export type ManagedContext = {
  baseInstructions: {
    content: string;
    source: "codex_native" | "managed";
    updatedAt: string | null;
  };
  systemPrompt: {
    content: string;
    updatedAt: string | null;
  };
  runtime: RuntimeStatus;
  skills: ManagedSkill[];
  mcpServers: ManagedMcpServer[];
};

export type ManagedMcpTool = {
  name: string;
  description: string;
  permission: string;
  trusted: boolean;
};

export type ManagedMcpEnvironment = {
  key: string;
  value: string;
  secret: boolean;
  configured?: boolean;
};

export type ManagedMcpServer = {
  name: string;
  displayName: string;
  category: "system" | "external";
  transport: "stdio" | "streamable_http";
  command: string;
  args: string[];
  url: string;
  bearerTokenEnvVar: string;
  oauthClientId: string;
  oauthResource: string;
  environment: ManagedMcpEnvironment[];
  enabled: boolean;
  mutable: boolean;
  deletable: boolean;
  status: string;
  permission: string;
  trusted: boolean;
  approval: string;
  tools: ManagedMcpTool[];
  envKeys: string[];
  message: string;
  createdAt?: string;
  updatedAt?: string;
  lastTestedAt?: string | null;
};

export type ManagedMcpInput = {
  name: string;
  displayName: string;
  transport: "stdio" | "streamable_http";
  command: string;
  args: string[];
  url: string;
  bearerTokenEnvVar: string;
  bearerToken?: string;
  oauthClientId: string;
  oauthResource: string;
  environment: ManagedMcpEnvironment[];
  enabled: boolean;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const payload = (await response.json().catch(() => ({}))) as T & {
    error?: string;
  };
  if (!response.ok) {
    throw new Error(payload.error || `system_request_failed:${response.status}`);
  }
  return payload;
}

export async function getSystemAccess(): Promise<SystemAccess> {
  const payload = await requestJson<{ access: SystemAccess }>("/api/system/access");
  return payload.access;
}

export async function bootstrapSystemAdministrator(): Promise<ManagedUser> {
  const payload = await requestJson<{ user: ManagedUser }>("/api/system/bootstrap", {
    method: "POST",
  });
  return payload.user;
}

export async function listManagedUsers(): Promise<ManagedUser[]> {
  const payload = await requestJson<{ users: ManagedUser[] }>("/api/system/users");
  return payload.users;
}

export async function updateManagedUser(
  userId: string,
  update: Partial<Pick<ManagedUser, "role" | "status">>,
): Promise<ManagedUser> {
  const payload = await requestJson<{ user: ManagedUser }>(
    `/api/system/users/${encodeURIComponent(userId)}`,
    { method: "PATCH", body: JSON.stringify(update) },
  );
  return payload.user;
}

export async function listManagedPrompts(): Promise<ManagedPrompt[]> {
  const payload = await requestJson<{ prompts: ManagedPrompt[] }>(
    "/api/system/prompts",
  );
  return payload.prompts;
}

export async function createPromptDraft(input: {
  promptKey: string;
  name: string;
  description: string | null;
  content: string;
}): Promise<ManagedPrompt> {
  const payload = await requestJson<{ prompt: ManagedPrompt }>("/api/system/prompts", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.prompt;
}

export async function publishPrompt(versionId: string): Promise<ManagedPrompt> {
  const payload = await requestJson<{ prompt: ManagedPrompt }>(
    `/api/system/prompts/${encodeURIComponent(versionId)}/publish`,
    { method: "POST" },
  );
  return payload.prompt;
}

export async function rollbackPrompt(versionId: string): Promise<ManagedPrompt> {
  const payload = await requestJson<{ prompt: ManagedPrompt }>(
    `/api/system/prompts/${encodeURIComponent(versionId)}/rollback`,
    { method: "POST" },
  );
  return payload.prompt;
}

export async function listManagedMcpServers(): Promise<ManagedMcpServer[]> {
  const payload = await requestJson<{ servers: ManagedMcpServer[] }>(
    "/api/system/mcp/servers",
  );
  return payload.servers;
}

export async function listManagedModelConnections(): Promise<
  ManagedModelConnection[]
> {
  const payload = await requestJson<{ connections: ManagedModelConnection[] }>(
    "/api/system/model-connections",
  );
  return payload.connections;
}

export async function createManagedModelConnection(
  input: ManagedModelConnectionInput,
): Promise<ManagedModelConnection> {
  const payload = await requestJson<{ connection: ManagedModelConnection }>(
    "/api/system/model-connections",
    { method: "POST", body: JSON.stringify(input) },
  );
  return payload.connection;
}

export async function updateManagedModelConnection(
  connectionName: string,
  input: Partial<ManagedModelConnectionInput>,
): Promise<ManagedModelConnection> {
  const payload = await requestJson<{ connection: ManagedModelConnection }>(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
  return payload.connection;
}

export async function deleteManagedModelConnection(
  connectionName: string,
): Promise<void> {
  const response = await fetch(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: string;
    };
    throw new Error(payload.error || `system_request_failed:${response.status}`);
  }
}

export async function revealManagedModelConnectionSecret(
  connectionName: string,
): Promise<string> {
  const payload = await requestJson<{ apiKey: string }>(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}/secret`,
  );
  return payload.apiKey;
}

export async function testManagedModelConnection(
  connectionName: string,
): Promise<{
  ok: boolean;
  status: string;
  message: string;
  latencyMs?: number;
}> {
  return requestJson(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}/test`,
    { method: "POST" },
  );
}

export async function setDefaultManagedModelConnection(
  connectionName: string,
): Promise<ManagedModelConnection> {
  const payload = await requestJson<{ connection: ManagedModelConnection }>(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}/default`,
    { method: "POST" },
  );
  return payload.connection;
}

export async function createManagedMcpServer(
  input: ManagedMcpInput,
): Promise<ManagedMcpServer> {
  const payload = await requestJson<{ server: ManagedMcpServer }>(
    "/api/system/mcp/servers",
    { method: "POST", body: JSON.stringify(input) },
  );
  return payload.server;
}

export async function updateManagedMcpServer(
  serverName: string,
  input: Partial<ManagedMcpInput>,
): Promise<ManagedMcpServer> {
  const payload = await requestJson<{ server: ManagedMcpServer }>(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
  return payload.server;
}

export async function updateMcpServerEnabled(
  serverName: string,
  enabled: boolean,
): Promise<ManagedMcpServer> {
  const payload = await requestJson<{ server: ManagedMcpServer }>(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}`,
    { method: "PATCH", body: JSON.stringify({ enabled }) },
  );
  return payload.server;
}

export async function deleteManagedMcpServer(serverName: string): Promise<void> {
  const response = await fetch(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(payload.error || `system_request_failed:${response.status}`);
  }
}

export async function revealManagedMcpSecrets(
  serverName: string,
): Promise<Record<string, string>> {
  const payload = await requestJson<{ secrets: Record<string, string> }>(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}/secrets`,
  );
  return payload.secrets;
}

export async function testManagedMcpServer(
  serverName: string,
): Promise<{
  ok: boolean;
  status: string;
  message: string;
  tools?: ManagedMcpTool[];
}> {
  return requestJson(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}/test`,
    { method: "POST" },
  );
}

export async function getRuntimePolicy(): Promise<RuntimeStatus> {
  const payload = await requestJson<{ runtime: RuntimeStatus }>(
    "/api/system/runtime-policy",
  );
  return payload.runtime;
}

export async function saveRuntimePolicy(
  policy: SystemRuntimePolicy,
): Promise<RuntimeStatus> {
  const payload = await requestJson<{ runtime: RuntimeStatus }>(
    "/api/system/runtime-policy",
    { method: "PUT", body: JSON.stringify(policy) },
  );
  return payload.runtime;
}

export async function getManagedContext(): Promise<ManagedContext> {
  const payload = await requestJson<{ context: ManagedContext }>(
    "/api/system/context",
  );
  return payload.context;
}

export async function saveManagedContext(
  input: { baseInstructions: string } | { systemPrompt: string },
): Promise<ManagedContext> {
  const payload = await requestJson<{ context: ManagedContext }>(
    "/api/system/context",
    { method: "PUT", body: JSON.stringify(input) },
  );
  return payload.context;
}
