import { describe, expect, test } from "vitest";

import {
  SystemRuntimePolicyError,
  validateSystemRuntimePolicy,
} from "@/modules/system/runtime-policy";

describe("system runtime policy", () => {
  test("accepts the supported safe execution policies", () => {
    expect(
      validateSystemRuntimePolicy({
        model: "MiniMax-M3",
        approvalMode: "deny_all",
        sandbox: "workspace_write",
        defaultToolsEnabled: false,
      }),
    ).toEqual({
      model: "MiniMax-M3",
      approvalMode: "deny_all",
      sandbox: "workspace_write",
      defaultToolsEnabled: false,
    });
  });

  test("rejects full access and unknown approval modes", () => {
    expect(() =>
      validateSystemRuntimePolicy({
        model: "MiniMax-M3",
        approvalMode: "never",
        sandbox: "full_access",
        defaultToolsEnabled: true,
      }),
    ).toThrow(SystemRuntimePolicyError);
  });

  test("requires a model name", () => {
    expect(() =>
      validateSystemRuntimePolicy({
        model: " ",
        approvalMode: "auto_review",
        sandbox: "read_only",
        defaultToolsEnabled: true,
      }),
    ).toThrow("runtime_model_required");
  });
});
