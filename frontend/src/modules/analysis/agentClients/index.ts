import { MockAgentClient } from "./mockClient";
import type { AgentClient } from "./types";

let client: AgentClient | null = null;

export function getAgentClient(): AgentClient {
  if (!client) {
    client = new MockAgentClient();
  }
  return client;
}

export * from "./types";
