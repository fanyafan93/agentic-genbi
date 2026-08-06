import type {
  ManagedModelConnection,
  ManagedModelConnectionInput,
  ManagedMcpInput,
  ManagedMcpServer,
  ManagedMcpTool,
  ManagedSkill,
} from "@/modules/system/system-api";
import type { SystemRuntimePolicy } from "@/modules/system/runtime-policy";

function backendBaseUrl(): string {
  return (
    process.env.GENBI_BACKEND_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://backend:8000"
  ).replace(/\/+$/, "");
}

function systemHeaders(actorId?: string, json = false): HeadersInit {
  const token = process.env.GENBI_SYSTEM_API_TOKEN?.trim();
  return {
    ...(token ? { "X-GenBI-System-Token": token } : {}),
    ...(actorId ? { "X-GenBI-Actor-Id": actorId } : {}),
    ...(json ? { "Content-Type": "application/json" } : {}),
  };
}

export class SystemBackendError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
  ) {
    super(code);
  }
}

async function backendJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${backendBaseUrl()}${path}`, {
    ...init,
    cache: "no-store",
  });
  const payload = (await response.json().catch(() => ({}))) as T & {
    detail?: string;
  };
  if (!response.ok) {
    throw new SystemBackendError(
      response.status,
      payload.detail || `system_backend_failed:${response.status}`,
    );
  }
  return payload;
}

export async function listSystemMcpServers(): Promise<ManagedMcpServer[]> {
  const payload = await backendJson<{ servers?: ManagedMcpServer[] }>(
    "/api/system/mcp/servers",
    {
    headers: systemHeaders(),
    },
  );
  return Array.isArray(payload.servers) ? payload.servers : [];
}

export async function listSystemModelConnections(): Promise<
  ManagedModelConnection[]
> {
  const payload = await backendJson<{ connections?: ManagedModelConnection[] }>(
    "/api/system/model-connections",
    { headers: systemHeaders() },
  );
  return Array.isArray(payload.connections) ? payload.connections : [];
}

export async function createSystemModelConnection(
  input: ManagedModelConnectionInput,
  actorId: string,
): Promise<ManagedModelConnection> {
  const payload = await backendJson<{ connection: ManagedModelConnection }>(
    "/api/system/model-connections",
    {
      method: "POST",
      headers: systemHeaders(actorId, true),
      body: JSON.stringify(input),
    },
  );
  return payload.connection;
}

export async function updateSystemModelConnection(
  connectionName: string,
  input: Partial<ManagedModelConnectionInput>,
  actorId: string,
): Promise<ManagedModelConnection> {
  const payload = await backendJson<{ connection: ManagedModelConnection }>(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}`,
    {
      method: "PATCH",
      headers: systemHeaders(actorId, true),
      body: JSON.stringify(input),
    },
  );
  return payload.connection;
}

export async function deleteSystemModelConnection(
  connectionName: string,
  actorId: string,
): Promise<void> {
  const response = await fetch(
    `${backendBaseUrl()}/api/system/model-connections/${encodeURIComponent(connectionName)}`,
    {
      method: "DELETE",
      headers: systemHeaders(actorId),
      cache: "no-store",
    },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new SystemBackendError(
      response.status,
      payload.detail || `system_backend_failed:${response.status}`,
    );
  }
}

export async function revealSystemModelConnectionSecret(
  connectionName: string,
): Promise<string> {
  const payload = await backendJson<{ apiKey: string }>(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}/secret`,
    { headers: systemHeaders() },
  );
  return payload.apiKey;
}

export async function testSystemModelConnection(
  connectionName: string,
  actorId?: string,
): Promise<{
  ok: boolean;
  status: string;
  message: string;
  latencyMs?: number;
}> {
  return backendJson(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}/test`,
    {
      method: "POST",
      headers: systemHeaders(actorId),
    },
  );
}

export async function setDefaultSystemModelConnection(
  connectionName: string,
  actorId: string,
): Promise<ManagedModelConnection> {
  const payload = await backendJson<{ connection: ManagedModelConnection }>(
    `/api/system/model-connections/${encodeURIComponent(connectionName)}/default`,
    {
      method: "POST",
      headers: systemHeaders(actorId),
    },
  );
  return payload.connection;
}

export async function createSystemMcpServer(
  input: ManagedMcpInput,
  actorId: string,
): Promise<ManagedMcpServer> {
  const payload = await backendJson<{ server: ManagedMcpServer }>(
    "/api/system/mcp/servers",
    {
      method: "POST",
      headers: systemHeaders(actorId, true),
      body: JSON.stringify(input),
    },
  );
  return payload.server;
}

export async function updateSystemMcpServer(
  serverName: string,
  input: Partial<ManagedMcpInput>,
  actorId: string,
): Promise<ManagedMcpServer> {
  const payload = await backendJson<{ server: ManagedMcpServer }>(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}`,
    {
      method: "PATCH",
      headers: systemHeaders(actorId, true),
      body: JSON.stringify(input),
    },
  );
  return payload.server;
}

export async function deleteSystemMcpServer(
  serverName: string,
  actorId: string,
): Promise<void> {
  const response = await fetch(
    `${backendBaseUrl()}/api/system/mcp/servers/${encodeURIComponent(serverName)}`,
    {
      method: "DELETE",
      headers: systemHeaders(actorId),
      cache: "no-store",
    },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new SystemBackendError(
      response.status,
      payload.detail || `system_backend_failed:${response.status}`,
    );
  }
}

export async function revealSystemMcpSecrets(
  serverName: string,
): Promise<Record<string, string>> {
  const payload = await backendJson<{ secrets: Record<string, string> }>(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}/secrets`,
    { headers: systemHeaders() },
  );
  return payload.secrets;
}

export async function testSystemMcpServer(
  serverName: string,
  actorId?: string,
): Promise<{
  ok: boolean;
  status: string;
  message: string;
  tools?: ManagedMcpTool[];
}> {
  return backendJson(
    `/api/system/mcp/servers/${encodeURIComponent(serverName)}/test`,
    {
      method: "POST",
      headers: systemHeaders(actorId),
    },
  );
}

export type SystemRuntimeStatus = SystemRuntimePolicy & {
  provider: string;
  enabled: boolean;
};

export async function getSystemRuntimeStatus(): Promise<SystemRuntimeStatus> {
  const response = await fetch(`${backendBaseUrl()}/api/system/runtime/policy`, {
    headers: systemHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`system_runtime_status_failed:${response.status}`);
  }
  return (await response.json()) as SystemRuntimeStatus;
}

export async function listSystemSkills(): Promise<ManagedSkill[]> {
  const payload = await backendJson<{ skills?: ManagedSkill[] }>(
    "/api/system/context/skills",
    { headers: systemHeaders() },
  );
  return Array.isArray(payload.skills) ? payload.skills : [];
}
