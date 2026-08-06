export type SystemApprovalMode = "auto_review" | "deny_all";
export type SystemSandboxMode = "read_only" | "workspace_write";

export type SystemRuntimePolicy = {
  approvalMode: SystemApprovalMode;
  sandbox: SystemSandboxMode;
  defaultToolsEnabled: boolean;
};

export class SystemRuntimePolicyError extends Error {
  constructor(
    public readonly code:
      | "runtime_approval_mode_invalid"
      | "runtime_sandbox_invalid"
      | "runtime_default_tools_invalid",
  ) {
    super(code);
    this.name = "SystemRuntimePolicyError";
  }
}

export function validateSystemRuntimePolicy(
  value: Record<string, unknown>,
): SystemRuntimePolicy {
  if (value.approvalMode !== "auto_review" && value.approvalMode !== "deny_all") {
    throw new SystemRuntimePolicyError("runtime_approval_mode_invalid");
  }
  if (value.sandbox !== "read_only" && value.sandbox !== "workspace_write") {
    throw new SystemRuntimePolicyError("runtime_sandbox_invalid");
  }
  if (typeof value.defaultToolsEnabled !== "boolean") {
    throw new SystemRuntimePolicyError("runtime_default_tools_invalid");
  }
  return {
    approvalMode: value.approvalMode,
    sandbox: value.sandbox,
    defaultToolsEnabled: value.defaultToolsEnabled,
  };
}
