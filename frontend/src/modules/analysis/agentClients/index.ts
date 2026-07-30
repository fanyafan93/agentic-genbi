import { BackendAnalysisAgentClient, getBackendAnalysisApiBaseUrl, shouldUseBackendAnalysisClient } from "./backendClient";
import { MockAgentClient } from "./mockClient";
import type { AgentClient } from "./types";

let client: AgentClient | null = null;

export function getAgentClient(): AgentClient {
  if (!client) {
    const apiBaseUrl = getBackendAnalysisApiBaseUrl();
    client = shouldUseBackendAnalysisClient() && apiBaseUrl
      ? new BackendAnalysisAgentClient(apiBaseUrl)
      : new MockAgentClient();
  }
  return client;
}

export * from "./types";
