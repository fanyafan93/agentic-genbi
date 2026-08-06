import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { getSystemRuntimeStatus } from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import {
  SystemRuntimePolicyError,
  validateSystemRuntimePolicy,
} from "@/modules/system/runtime-policy";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    return NextResponse.json({ runtime: await getSystemRuntimeStatus() });
  } catch (error) {
    return systemRouteError(error);
  }
}

export async function PUT(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const policy = validateSystemRuntimePolicy(
      (await request.json()) as Record<string, unknown>,
    );
    await prisma.$transaction([
      prisma.systemSetting.upsert({
        where: { key: "runtime.policy" },
        create: {
          key: "runtime.policy",
          value: {
            approval_mode: policy.approvalMode,
            sandbox: policy.sandbox,
            default_tools_enabled: policy.defaultToolsEnabled,
          },
          updatedById: session.user.id,
        },
        update: {
          value: {
            approval_mode: policy.approvalMode,
            sandbox: policy.sandbox,
            default_tools_enabled: policy.defaultToolsEnabled,
          },
          updatedById: session.user.id,
        },
      }),
      prisma.systemAuditLog.create({
        data: {
          actorId: session.user.id,
          action: "runtime.policy.update",
          targetType: "runtime_policy",
          targetId: "default",
          after: policy,
        },
      }),
    ]);
    const current = await getSystemRuntimeStatus();
    return NextResponse.json({ runtime: { ...current, ...policy } });
  } catch (error) {
    if (error instanceof SystemRuntimePolicyError) {
      return NextResponse.json({ error: error.code }, { status: 422 });
    }
    return systemRouteError(error);
  }
}
