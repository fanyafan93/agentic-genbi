import { describe, expect, test } from "vitest";

import {
  SystemContextSettingsError,
  validateSystemContextUpdate,
} from "@/modules/system/system-context-settings";

describe("system context settings", () => {
  test("accepts direct base instruction and system prompt updates", () => {
    expect(validateSystemContextUpdate({
      baseInstructions: "  你是企业数据分析助手。  ",
    })).toEqual({
      baseInstructions: "你是企业数据分析助手。",
    });
    expect(validateSystemContextUpdate({
      systemPrompt: "  先核验真实数据。  ",
    })).toEqual({
      systemPrompt: "先核验真实数据。",
    });
  });

  test("requires exactly one non-empty instruction field", () => {
    expect(() => validateSystemContextUpdate({})).toThrow(
      SystemContextSettingsError,
    );
    expect(() => validateSystemContextUpdate({
      baseInstructions: "",
      systemPrompt: "同时更新",
    })).toThrow("context_update_invalid");
  });
});
