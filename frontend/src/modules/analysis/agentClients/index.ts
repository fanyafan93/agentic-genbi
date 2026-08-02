import { BackendAnalysisAgentClient, getBackendAnalysisApiBaseUrl, shouldUseBackendAnalysisClient } from "./backendClient";
import type { AgentClient } from "./types";

let client: AgentClient | null = null;

export function getAgentClient(): AgentClient {
  if (!client) {
    const apiBaseUrl = getBackendAnalysisApiBaseUrl();
    if (!shouldUseBackendAnalysisClient() || !apiBaseUrl) {
      throw new Error("Analysis backend is not configured.");
    }
    client = new BackendAnalysisAgentClient(apiBaseUrl);
  }
  return client;
}

export * from "./types";
