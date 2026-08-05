import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { PrismaSystemPromptRepository } from "@/modules/system/server/prisma-system-prompt-repository";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { SystemPromptManagementService } from "@/modules/system/server/system-prompt-management";
import { systemRouteError } from "@/modules/system/server/system-route-response";

type RouteContext = { params: Promise<{ versionId: string }> };

export async function POST(_: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { versionId } = await context.params;
  try {
    const prompt = await prisma.$transaction(async (transaction) => {
      await transaction.$executeRaw`SELECT pg_advisory_xact_lock(hashtext('genbi_system_prompt_management'))`;
      await requireSystemAdministrator(session.user.id, transaction);
      const published = await new SystemPromptManagementService(
        new PrismaSystemPromptRepository(transaction),
      ).publish(session.user.id, versionId);
      await transaction.systemAuditLog.create({
        data: {
          actorId: session.user.id,
          action: "prompt.publish",
          targetType: "system_prompt",
          targetId: published.id,
          after: {
            promptKey: published.promptKey,
            version: published.version,
            status: published.status,
          },
        },
      });
      return published;
    });
    return NextResponse.json({ prompt });
  } catch (error) {
    return systemRouteError(error);
  }
}
