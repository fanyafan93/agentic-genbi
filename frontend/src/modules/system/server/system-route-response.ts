import { NextResponse } from "next/server";

import { SystemPromptManagementError } from "./system-prompt-management";
import { SystemUserManagementError } from "./system-user-management";

export function systemRouteError(error: unknown): NextResponse {
  if (error instanceof SystemUserManagementError) {
    const status =
      error.code === "administrator_required"
        ? 403
        : error.code === "user_not_found"
          ? 404
          : 409;
    return NextResponse.json({ error: error.code }, { status });
  }
  if (error instanceof SystemPromptManagementError) {
    const status = error.code === "prompt_version_not_found" ? 404 : 422;
    return NextResponse.json({ error: error.code }, { status });
  }
  console.error("system_management_request_failed", error);
  return NextResponse.json({ error: "system_management_request_failed" }, { status: 500 });
}
