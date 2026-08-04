import {
  BackendAnalysisAgentClient,
  createBackendAnalysisAgentClient,
  shouldUseBackendAnalysisClient,
} from "./backendClient";
import type { AgentClient } from "./types";

/**
 * Construct a fresh analysis client.
 *
 * The previous ``getAgentClient()`` returned a module-level singleton whose
 * hidden ``threadId`` and ``AbortController`` fields caused cross-task
 * interference (opening one task could cancel another). Per the multi-task
 * contract, each consumer (``useFlow``, scripts) now owns its own client;
 * the singleton is gone on purpose, and so are ``cancel()`` and any other
 * lifecycle methods on the client surface.
 */
export function getAgentClient(): AgentClient {
  return createBackendAnalysisAgentClient();
}

// Convenience re-exports so existing call sites keep working without a
// second import.
export {
  BackendAnalysisAgentClient,
  createBackendAnalysisAgentClient,
  shouldUseBackendAnalysisClient,
};

export * from "./types";
