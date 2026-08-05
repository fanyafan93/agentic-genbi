import { BackendAnalysisAgentClient, getBackendAnalysisApiBaseUrl, shouldUseBackendAnalysisClient } from "./backendClient";
import type { AgentClient } from "./types";

const clients = new Map<string, AgentClient>();

export function getAgentClient(scopeKey = "default"): AgentClient {
  let client = clients.get(scopeKey);
  if (!client) {
    const apiBaseUrl = getBackendAnalysisApiBaseUrl();
    if (!shouldUseBackendAnalysisClient() || !apiBaseUrl) {
      throw new Error("Analysis backend is not configured.");
    }
    client = new BackendAnalysisAgentClient(apiBaseUrl);
    clients.set(scopeKey, client);
  }
  return client;
}

export * from "./types";
