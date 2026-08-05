import type { BackendMcpServer } from "@/modules/analysis/agentClients/backendClient";
import type { SystemRuntimePolicy } from "@/modules/system/runtime-policy";

function backendBaseUrl(): string {
  return (
    process.env.GENBI_BACKEND_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://backend:8000"
  ).replace(/\/+$/, "");
}

function systemHeaders(): HeadersInit {
  const token = process.env.GENBI_SYSTEM_API_TOKEN?.trim();
  return token ? { "X-GenBI-System-Token": token } : {};
}

export async function listSystemMcpServers(): Promise<BackendMcpServer[]> {
  const response = await fetch(`${backendBaseUrl()}/api/system/mcp/servers`, {
    headers: systemHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`system_mcp_list_failed:${response.status}`);
  }
  const payload = (await response.json()) as { servers?: BackendMcpServer[] };
  return Array.isArray(payload.servers) ? payload.servers : [];
}

export async function testSystemMcpServer(
  serverName: string,
): Promise<{ ok: boolean; status: string; message: string }> {
  const response = await fetch(
    `${backendBaseUrl()}/api/system/mcp/servers/${encodeURIComponent(serverName)}/test`,
    {
      method: "POST",
      headers: systemHeaders(),
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new Error(`system_mcp_test_failed:${response.status}`);
  }
  return (await response.json()) as {
    ok: boolean;
    status: string;
    message: string;
  };
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
