import type { BackendMcpServer } from "@/modules/analysis/agentClients/backendClient";
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

export async function listManagedMcpServers(): Promise<BackendMcpServer[]> {
  const payload = await requestJson<{ servers: BackendMcpServer[] }>(
    "/api/system/mcp/servers",
  );
  return payload.servers;
}

export async function updateMcpServerEnabled(
  serverName: string,
  enabled: boolean,
): Promise<void> {
  await requestJson(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}`,
    { method: "PATCH", body: JSON.stringify({ enabled }) },
  );
}

export async function testManagedMcpServer(
  serverName: string,
): Promise<{ ok: boolean; status: string; message: string }> {
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
