import { describe, expect, it } from "vitest";

import { mapFeishuProfile } from "../src/modules/auth/feishu-profile";

describe("mapFeishuProfile", () => {
  it("maps Feishu profile to an Auth.js user with the default role", () => {
    expect(
      mapFeishuProfile({
        union_id: "union_1",
        open_id: "open_1",
        name: "Jason",
        email: "jason@example.com",
        avatar_url: "https://example.com/avatar.png",
      }),
    ).toEqual({
      id: "union_1",
      name: "Jason",
      email: "jason@example.com",
      image: "https://example.com/avatar.png",
      role: "user",
    });
  });

  it("rejects a Feishu profile without a stable account id", () => {
    expect(() => mapFeishuProfile({ name: "No Id" })).toThrow("feishu_profile_missing_id");
  });
});
