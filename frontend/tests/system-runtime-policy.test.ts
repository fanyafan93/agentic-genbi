import { describe, expect, test } from "vitest";

import {
  SystemRuntimePolicyError,
  validateSystemRuntimePolicy,
} from "@/modules/system/runtime-policy";

describe("system runtime policy", () => {
  test("accepts the supported safe execution policies", () => {
    expect(
      validateSystemRuntimePolicy({
        approvalMode: "deny_all",
        sandbox: "workspace_write",
        defaultToolsEnabled: false,
      }),
    ).toEqual({
      approvalMode: "deny_all",
      sandbox: "workspace_write",
      defaultToolsEnabled: false,
    });
  });

  test("rejects full access and unknown approval modes", () => {
    expect(() =>
      validateSystemRuntimePolicy({
        approvalMode: "never",
        sandbox: "full_access",
        defaultToolsEnabled: true,
      }),
    ).toThrow(SystemRuntimePolicyError);
  });

  test("keeps model selection outside the runtime policy", () => {
    expect(
      validateSystemRuntimePolicy({
        model: "legacy-model-must-not-be-persisted",
        approvalMode: "auto_review",
        sandbox: "read_only",
        defaultToolsEnabled: true,
      }),
    ).toEqual({
      approvalMode: "auto_review",
      sandbox: "read_only",
      defaultToolsEnabled: true,
    });
  });
});
